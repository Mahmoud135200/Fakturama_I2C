from __future__ import annotations

from decimal import Decimal
from typing import Optional

from ..models import OrderData
from . import decisions as D
from . import pages
from .app import App
from .report import ManualReviewRequired, RunReport
from .wait import wait_until


def run(order: OrderData, app: App, out_dir: str,
        seed_payments: bool = True) -> RunReport:
    report = RunReport(out_dir=out_dir)

    try:
        dismissed = pages.dismiss_leftover_dialogs(app)
        if dismissed:
            report.log(
                "0 clear leftover modal dialogs",
                True,
                f"cancelled {dismissed} from a previous run",
            )

        if seed_payments:
            seed_payment_methods(app, report)
        _run(order, app, report)
        report.ok = True

    except ManualReviewRequired as e:
        report.ok = False
        report.error = str(e)

        if e.screenshot is None:
            e.screenshot = app.screenshot(
                report.out_dir,
                f"stop-{e.step}",
            )

        report.log(
            e.step,
            False,
            str(e),
            e.screenshot,
        )

    except Exception as e:  # noqa: BLE001
        report.ok = False
        report.error = f"unexpected error: {e!r}"

        try:
            shot = app.screenshot(
                report.out_dir,
                "unexpected-error",
            )
        except Exception:
            shot = None

        report.log(
            "unexpected",
            False,
            str(e),
            shot,
        )

    finally:
        report.save()

    return report


def _shot(
    app: App,
    report: RunReport,
    name: str,
) -> str:
    return app.screenshot(
        report.out_dir,
        name,
    )


def _run(
    order: OrderData,
    app: App,
    report: RunReport,
) -> None:

    editor = pages.OrderEditor.open_new(app)

    no = editor.read_no()
    report.order_no = no

    report.log(
        "1.3-1.4 open New Order",
        True,
        f"proposed No. {no}",
    )

    editor.set_date(order.order_date.isoformat())
    editor.set_cust_ref(order.external_reference)

    report.log(
        "1.5-1.6 set Date/Cust.Ref.",
        True,
    )

    editor.set_price_mode_net()
    editor.set_vat_mode_with_vat()

    report.log(
        "1.7 price mode Net / VAT With VAT",
        True,
    )

    # 2. Debtor

    _resolve_debtor(
        order,
        app,
        editor,
        report,
    )

    # 3. Products

    running = RunningTotals()

    for item in order.items:
        _resolve_and_add_item(
            order,
            item,
            app,
            editor,
            report,
            running,
        )

    # 4. Complete and save Order

    _confirm_order_contents(order, app, editor, report)

    _confirm_order_level_defaults(app, editor, report)

    net, vat, gross = editor.totals()

    decision = D.totals_match(
        _dec(net),
        _dec(vat),
        _dec(gross),
        order.totals.net,
        order.totals.vat,
        order.totals.gross,
    )

    if decision.action == "review":
        raise ManualReviewRequired(
            "4.3 totals check",
            str(
                (
                    order.totals.net,
                    order.totals.vat,
                    order.totals.gross,
                )
            ),
            str(
                (
                    net,
                    vat,
                    gross,
                )
            ),
            _shot(
                app,
                report,
                "4.3-totals-mismatch",
            ),
        )

    report.log(
        "4.3 confirm totals",
        True,
        f"net={net} vat={vat} gross={gross} (source "
        f"{order.totals.net}/{order.totals.vat}/{order.totals.gross})",
    )

    # 4.4 -- once, and only once.
    saved_no = editor.save()
    if saved_no:
        report.order_no = saved_no
        no = saved_no

    report.log(
        "4.4 save Order",
        True,
        f"saved as {no}",
        screenshot=_shot(
            app,
            report,
            "4.4-order-saved",
        ),
    )

    _verify_saved_order(order, no, app, report, editor)

    invoice = editor.create_invoice()

    report.log(
        "4.6-4.7 create linked Invoice from the saved Order",
        True,
        "clicked Invoice in 'Create a follow-up document'; New Invoice editor open",
        screenshot=_shot(app, report, "4.7-linked-invoice"),
    )

    _confirm_invoice_copied_from_order(order, app, invoice, report)

    if not invoice.set_payment_method(order.payment.method):
        raise ManualReviewRequired(
            "5.2 invoice payment method",
            order.payment.method,
            f"not offered in the Invoice's dropdown (it reads "
            f"{invoice.read_payment_method()!r})",
            _shot(app, report, "5.2-payment-method-missing"),
        )

    report.log(
        "5.2 Invoice payment method",
        True,
        f"{invoice.read_payment_method()!r}",
    )

    if order.payment.is_paid:
        state = invoice.set_paid(
            order.payment.payment_date.isoformat(),
            str(order.totals.gross),
        )

        if state.get("paid") != "yes":
            raise ManualReviewRequired(
                "5.3 apply PAID status",
                "the 'paid' box ticked",
                f"it reads {state}",
                _shot(app, report, "5.3-paid-not-applied"),
            )

        report.log(
            "5.3 set paid + payment date + Value",
            True,
            f"date {order.payment.payment_date.isoformat()}, "
            f"Value {order.totals.gross}; editor reads {state}",
        )

    else:
        if invoice.is_paid():
            raise ManualReviewRequired(
                "5.3 leave Invoice unpaid",
                "the 'paid' box clear",
                f"it is ticked, but the source status is "
                f"{order.payment.status!r}",
                _shot(app, report, "5.3-unexpectedly-paid"),
            )
        report.log(
            "5.3 leave unpaid",
            True,
            f"source Paid Status is {order.payment.status!r}",
        )

    inv_no = invoice.save()
    report.invoice_no = inv_no

    report.log(
        "5.4 save Invoice",
        True,
        f"saved as {inv_no}",
        screenshot=_shot(app, report, "5.4-invoice-saved"),
    )

    _verify_saved_invoice(order, no, inv_no, app, invoice, report)


def _confirm_invoice_copied_from_order(
    order: OrderData,
    app: App,
    invoice: "pages.InvoiceEditor",
    report: RunReport,
) -> None:
    problems: list[str] = []

    cust_ref = invoice.read_cust_ref()
    if order.external_reference not in cust_ref:
        problems.append(
            f"Cust.Ref. {cust_ref!r} != {order.external_reference!r}")

    d = order.debtor
    if not invoice.confirm_addresses_populated((d.company, d.last_name)):
        problems.append(
            f"the address block does not show {d.company} / {d.last_name}")

    vat_mode = invoice.vat_mode()
    if vat_mode and vat_mode != "With VAT":
        problems.append(f"VAT mode {vat_mode!r} != 'With VAT'")

    net, vat, gross = invoice.totals()
    totals = D.totals_match(
        _dec(net), _dec(vat), _dec(gross),
        order.totals.net, order.totals.vat, order.totals.gross,
    )
    totals_agree = totals.action != "review"
    if not totals_agree:
        problems.append(totals.reason)

    line_proof = ""

    rows = invoice.read_all_item_rows()
    missing = [i.sku for i in order.items
               if invoice.find_item_row(i.sku, rows) is None]

    if not missing:
        line_proof = f"all {len(order.items)} line(s) read from the Items grid"
    elif rows:
        # The grid WAS readable and a line is genuinely absent.
        for sku in missing:
            problems.append(f"no Invoice line for {sku}")
        info = invoice.dump_last_items_capture(report.out_dir, "5.1-items-read")
        if info:
            problems.append(
                f"last read: band{info['band']} rows={info['rows']}")
    elif totals_agree:
        line_proof = (
            f"Items grid not rendered on this Invoice, so the {len(order.items)} "
            f"line(s) were verified through the totals Fakturama derives from "
            f"them (net {net}, VAT {vat}, total {gross} -- all three match the "
            f"source exactly)")
    else:
        problems.append(
            f"the Items grid could not be read and the totals do not match "
            f"either, so nothing confirms the {len(order.items)} line(s) copied")
        info = invoice.dump_last_items_capture(report.out_dir, "5.1-items-read")
        if info:
            problems.append(
                f"items read: pane{info['pane_rect']} band{info['band']} "
                f"columns={info['columns']} rows={info['rows']}")

    if problems:
        raise ManualReviewRequired(
            "5.1 confirm the Invoice copied the Order",
            (
                f"Cust.Ref. {order.external_reference}, {d.company}'s addresses, "
                f"With VAT, {len(order.items)} line(s), totals "
                f"{order.totals.net}/{order.totals.vat}/{order.totals.gross}"
            ),
            "; ".join(problems),
            _shot(app, report, "5.1-invoice-not-copied"),
        )

    report.log(
        "5.1 confirm Invoice copied from Order",
        True,
        f"No. {invoice.read_no()!r} (left as proposed); Cust.Ref. {cust_ref!r}; "
        f"VAT mode {vat_mode!r}; net={net} vat={vat} gross={gross}; "
        f"lines: {line_proof}",
    )


def _verify_saved_invoice(
    order: OrderData,
    order_no: str,
    invoice_no: str,
    app: App,
    invoice: "pages.InvoiceEditor",
    report: RunReport,
) -> None:
    docs = pages.DocumentsView(app)

    try:
        docs.open()

        docs.search(order.external_reference)
        rows = docs.rows()
    except Exception as exc:
        raise ManualReviewRequired(
            "5.5 verify Documents list",
            f"Order {order_no} and Invoice {invoice_no} under Cust.Ref. "
            f"{order.external_reference}",
            f"could not open/read/filter the Documents Data Browser: {exc}",
            _shot(app, report, "5.5-documents-unreadable"),
        ) from exc

    order_row = next(
        (r for r in rows if _same_document_no(r.get("Document"), order_no)), None)
    invoice_row = next(
        (r for r in rows if _same_document_no(r.get("Document"), invoice_no)), None)

    if order_row is None or invoice_row is None:
        raise ManualReviewRequired(
            "5.5 verify Documents list",
            f"rows for Order {order_no} and Invoice {invoice_no}",
            f"found order={_visible([order_row]) if order_row else None} "
            f"invoice={_visible([invoice_row]) if invoice_row else None} "
            f"among {_visible(rows)}",
            _shot(app, report, "5.5-documents-verify"),
        )

    problems: list[str] = []

    for label, row, expect_open in (("Order", order_row, True),
                                    ("Invoice", invoice_row, False)):
        total = D.parse_number(row.get("Total"))
        if total is not None and total != order.totals.gross:
            problems.append(f"{label} Total {row.get('Total')!r} != "
                            f"{order.totals.gross}")
        state = (row.get("State") or "").casefold()
        if expect_open and state and "open" not in state:
            problems.append(f"{label} State {row.get('State')!r} is not open")
        if not expect_open and state and order.payment.is_paid \
                and "paid" not in state:
            problems.append(f"{label} State {row.get('State')!r} is not paid")

    if problems:
        raise ManualReviewRequired(
            "5.5 verify Documents list",
            f"Order {order_no} open and Invoice {invoice_no} "
            f"{'paid' if order.payment.is_paid else 'saved'}, both totalling "
            f"{order.totals.gross}",
            "; ".join(problems),
            _shot(app, report, "5.5-documents-mismatch"),
        )

    persisted = invoice.read_paid_state()

    if order.payment.is_paid and persisted.get("paid") != "yes":
        raise ManualReviewRequired(
            "5.6 confirm persisted payment",
            "the saved Invoice still marked paid",
            f"it reads {persisted}",
            _shot(app, report, "5.6-payment-not-persisted"),
        )

    report.log(
        "5.5-5.6 verify Invoice and source Order",
        True,
        f"order={_visible([order_row])[0]}; invoice={_visible([invoice_row])[0]}; "
        f"saved Invoice reads {persisted}",
        screenshot=_shot(app, report, "5.5-documents"),
    )

    report.log(
        "5.7 flow ends -- no Delivery/Correction/Dunning created",
        True,
    )


def _confirm_order_contents(
    order: OrderData,
    app: App,
    editor: "pages.OrderEditor",
    report: RunReport,
) -> None:
    d = order.debtor

    if not editor.confirm_addresses_populated((d.company, d.last_name)):
        raise ManualReviewRequired(
            "4.1 confirm Debtor addresses",
            f"the Order's address block showing {d.company} / {d.last_name}",
            "it does not",
            _shot(app, report, "4.1-addresses-mismatch"),
        )

    rows = editor.read_item_rows(order.items[-1].sku if order.items else "")
    details: list[str] = []

    for item in order.items:
        row = editor.find_item_row(item.sku, rows)
        if row is None:
            raise ManualReviewRequired(
                f"4.1 confirm line {item.sku}",
                f"an Items row for {item.sku}",
                f"the Items table shows {_visible(rows)}",
                _shot(app, report, f"4.1-line-missing-{item.sku}"),
            )
        check = D.match_order_line(
            row, item.quantity, item.unit_net, item.discount_pct,
            item.vat_pct, item.computed_line_net,
        )
        details.append(f"{item.sku}: {check.action} ({check.reason})")

    report.log(
        "4.1 confirm Debtor addresses + every Product line",
        True,
        f"{len(order.items)} line(s) present; grid read -> " + "; ".join(details),
    )


def _confirm_order_level_defaults(
    app: App,
    editor: "pages.OrderEditor",
    report: RunReport,
) -> None:
    settings = editor.order_level_settings()
    discount = D.parse_number(settings.get("Discount"))

    if discount is None or discount != 0:
        editor.set_order_discount_zero()
        settings = editor.order_level_settings()
        discount = D.parse_number(settings.get("Discount"))
        if discount is None or discount != 0:
            raise ManualReviewRequired(
                "4.2 order-level Discount",
                "0%",
                f"{settings.get('Discount')!r}",
                _shot(app, report, "4.2-order-discount"),
            )

    shipping = (settings.get("Shipping") or "").strip()
    if shipping and shipping != editor.NO_SHIPPING:
        raise ManualReviewRequired(
            "4.2 order-level Shipping",
            editor.NO_SHIPPING,
            f"{shipping!r} -- the source document supplies no shipping cost",
            _shot(app, report, "4.2-order-shipping"),
        )

    report.log(
        "4.2 order-level Discount 0% / Shipping free",
        True,
        f"Discount={settings.get('Discount')!r} Shipping={shipping!r}; any "
        f"shipping cost would also show up in the 4.3 totals comparison",
    )


def _verify_saved_order(
    order: OrderData,
    order_no: str,
    app: App,
    report: RunReport,
    editor: "pages.OrderEditor",
) -> None:
    docs = pages.DocumentsView(app)

    try:
        docs.open()

        docs.search(order.external_reference)

        rows = docs.rows()
    except Exception as exc:
        raise ManualReviewRequired(
            "4.5 verify saved Order",
            f"the Documents list showing Order {order_no}",
            f"could not open/read/filter the Documents Data Browser: {exc}",
            _shot(app, report, "4.5-documents-unreadable"),
        ) from exc

    if not rows:
        raise ManualReviewRequired(
            "4.5 verify saved Order",
            f"a Documents row for Cust.Ref. {order.external_reference!r}",
            "the filtered list came back empty -- the Order did not persist",
            _shot(app, report, "4.5-order-row-missing"),
        )

    matches = [r for r in rows if _same_document_no(r.get("Document"), order_no)]

    if len(matches) != 1:
        raise ManualReviewRequired(
            "4.5 verify saved Order",
            f"exactly one Documents row for Cust.Ref. "
            f"{order.external_reference!r} numbered {order_no}",
            f"found {len(matches)} of {len(rows)} filtered row(s): {_visible(rows)}",
            _shot(app, report, "4.5-order-row"),
        )

    row = matches[0]
    problems: list[str] = []

    shown_date = (row.get("Date") or "").strip()
    date_source = "Documents list"
    if not shown_date:
        date_source = "the Order editor's Date field"
        try:
            shown_date = editor.read_date()
        except Exception as exc:
            shown_date = ""
            date_source = f"{date_source} (unreadable: {exc})"

    if not shown_date:
        problems.append(
            f"could not read the Order date from the Documents list or from "
            f"{date_source}, so it could not be verified")
    elif not _date_matches(shown_date, order.order_date):
        problems.append(
            f"Date {shown_date!r} (read from {date_source}) is not "
            f"{order.order_date.isoformat()}")

    total = D.parse_number(row.get("Total"))
    if total is not None and total != order.totals.gross:
        problems.append(f"Total {row.get('Total')!r} != {order.totals.gross}")

    state = (row.get("State") or "").casefold()
    if state and "open" not in state:
        problems.append(f"State {row.get('State')!r} is not open")

    if problems:
        raise ManualReviewRequired(
            "4.5 verify saved Order",
            f"Order {order_no} dated {order.order_date.isoformat()}, open, "
            f"Total {order.totals.gross}, Cust.Ref. {order.external_reference}",
            "; ".join(problems),
            _shot(app, report, "4.5-order-row-mismatch"),
        )

    unchecked = [c for c in ("State", "Total") if not (row.get(c) or "").strip()]

    report.log(
        "4.5 verify saved Order in Data > Documents",
        True,
        f"one row for Cust.Ref. {order.external_reference}: {_visible([row])[0]}"
        + (f"; {unchecked} are rendered past this view's right edge and were "
           f"verified in the Order editor at 4.3 instead" if unchecked else ""),
        screenshot=_shot(app, report, "4.5-documents"),
    )


def _same_document_no(shown: Optional[str], expected: str) -> bool:
    def fold(value: str) -> str:
        return (value or "").strip().upper().replace("O", "0").replace(" ", "").replace("|", "")

    shown_folded, expected_folded = fold(shown or ""), fold(expected)
    return bool(expected_folded) and expected_folded in shown_folded


def _date_matches(shown: str, when) -> bool:
    text = (shown or "").casefold().replace(" ", "")
    for pattern in ("%b %d, %Y", "%b %-d, %Y", "%d.%m.%Y", "%Y-%m-%d"):
        try:
            rendered = when.strftime(pattern)
        except ValueError:
            continue
        if rendered.casefold().replace(" ", "") in text:
            return True
    return False


def _dec(s) -> Decimal:
    if s is None:
        return Decimal("NaN")

    try:
        return Decimal(
            str(s)
            .replace("€", "")
            .replace("$", "")
            .strip()
        )

    except Exception:
        return Decimal("NaN")


def _resolve_debtor(
    order: OrderData,
    app: App,
    editor: "pages.OrderEditor",
    report: RunReport,
) -> None:
    d = order.debtor

    decision, attempts, dialog = _search_existing_debtor(editor, d)

    report.log(
        "2.2 search existing Debtor",
        True,
        "; ".join(attempts),
    )

    # Ambiguous match

    if decision.action == "review":
        dialog_shot = _shot(
            app,
            report,
            "2.3-debtor-ambiguous",
        )

        raise ManualReviewRequired(
            "2.3 Debtor match",
            f"one exact match for {d.company}",
            decision.reason,
            dialog_shot,
        )

    # Existing exact Debtor

    if decision.action == "select":
        dialog.select_row(decision.row)
        dialog.ok()

        if not editor.confirm_addresses_populated(
            (d.company, d.last_name)
        ):
            raise ManualReviewRequired(
                "2.4 confirm addresses populated",
                f"Invoice/Delivery address showing {d.company} / {d.last_name}",
                "address not populated with the selected Debtor's data",
                _shot(
                    app,
                    report,
                    "2.4-addresses-not-populated",
                ),
            )

        report.log(
            "2.1-2.4 select existing Debtor",
            True,
            f"matched row {decision.row}"
            + (" (a grid cell was ellipsed, so that field was matched by "
               "prefix; all other fields matched exactly and the hit was unique)"
               if decision.truncated else ""),
        )

        return

    # No exact Debtor -> create

    dialog.cancel()

    report.log(
        "2.3 no exact Debtor match -> create",
        True,
    )

    deb = pages.DebtorEditor.open_new(app)

    deb.set_company(d.company)

    deb.set_names(
        d.first_name,
        d.last_name,
    )

    deb.fill_main_address(
        d.billing.street,
        d.billing.zip,
        d.billing.city,
        d.billing.country,
        d.email,
        d.phone,
    )

    same_address = d.same_billing_and_delivery

    deb.set_address_role_invoice(
        also_delivery=same_address,
    )

    report.log(
        "2.6-2.8 fill Debtor + main address",
        True,
        (
            "Main address roles: Invoice"
            + (" + Delivery (billing == delivery)" if same_address else "")
            + (
                ""
                if same_address
                else (
                    f" only; billing != delivery "
                    f"({d.billing.street}, {d.billing.zip} vs "
                    f"{d.delivery.street}, {d.delivery.zip})"
                )
            )
        ),
    )

    # 2.9 Miscellaneous

    deb.goto_miscellaneous()

    deb.set_alias(d.alias)

    deb.set_discount_zero()

    deb.set_net_or_gross_net()

    report.log(
        "2.9 Miscellaneous: alias/discount/net",
        True,
    )

    try:
        payment_exists = deb.set_payment_method(
            order.payment.method,
        )
    except Exception as e:
        raise ManualReviewRequired(
            "2.10 payment method lookup",
            order.payment.method,
            f"Could not verify payment method selector: {e}",
            _shot(
                app,
                report,
                "2.10-payment-method-lookup-failure",
            ),
        ) from e

    if not payment_exists:
        raise ManualReviewRequired(
            "2.10 payment method",
            f"{order.payment.method!r} selectable in the Debtor's Payment dropdown",
            "not offered. Seeding creates Bank Transfer / Credit Card / "
            "SEPA Direct Debit up front (2.10.3-2.10.5); run "
            "'python -m fakturama_i2c seed-payments' if it was skipped, or "
            "check the extracted method matches the 2.10.4 mapping",
            _shot(
                app,
                report,
                "2.10-payment-method-not-offered",
            ),
        )

    report.log(
        "2.10 Payment method set",
        True,
        f"selected {order.payment.method!r} (created up front by seeding)",
    )

    try:
        company = deb.save()

    except pages.DuplicateContact as e:
        deb.discard()

        report.log(
            "2.11 save Debtor",
            False,
            f"Fakturama reported a duplicate contact: {e}",
        )

        _select_existing_after_duplicate(
            order,
            app,
            editor,
            report,
        )

        return

    report.note_created(
        "debtor",
        company,
    )

    report.log(
        "2.11 save Debtor",
        True,
        screenshot=_shot(
            app,
            report,
            "2.11-debtor-saved",
        ),
    )

    decision2, attempts2, dialog2 = _search_existing_debtor(editor, d)

    report.log(
        "2.12 search newly saved Debtor",
        True,
        "; ".join(attempts2),
    )

    if decision2.action != "select":
        raise ManualReviewRequired(
            "2.12 reselect new Debtor",
            company,
            f"saved Debtor not re-findable ({decision2.action}): "
            f"{decision2.reason or attempts2}",
            _shot(
                app,
                report,
                "2.12-new-debtor-not-found",
            ),
        )

    dialog2.select_row(decision2.row)
    dialog2.ok()

    if not editor.confirm_addresses_populated(
        (d.company, d.last_name)
    ):
        raise ManualReviewRequired(
            "2.13 confirm new Debtor selection",
            f"Invoice/Delivery address showing {d.company} / {d.last_name}",
            "address not populated with the new Debtor's data",
            _shot(
                app,
                report,
                "2.13-addresses-not-populated",
            ),
        )

    report.log(
        "2.12-2.13 reselect + confirm new Debtor",
        True,
    )


def _select_existing_after_duplicate(
    order: OrderData,
    app: App,
    editor: "pages.OrderEditor",
    report: RunReport,
) -> None:
    d = order.debtor

    dialog = editor.open_address_selector()

    dialog.search(d.last_name)

    rows = dialog.rows_stable()

    candidates = [
        r
        for r in rows
        if r.get("First Name", "").strip()
        == d.first_name.strip()
        and r.get("Name", "").strip()
        == d.last_name.strip()
    ]

    exact = [
        r
        for r in candidates
        if r.get("Company", "").strip()
        == d.company.strip()
        and r.get("ZIP", "").strip()
        == d.billing.zip.strip()
        and r.get("City", "").strip()
        == d.billing.city.strip()
    ]

    if len(exact) == 1:
        dialog.select_row(exact[0])
        dialog.ok()

        if not editor.confirm_addresses_populated():
            raise ManualReviewRequired(
                "2.12 select existing Debtor after duplicate",
                "Invoice/Delivery address shown",
                "address tab not found",
                _shot(
                    app,
                    report,
                    "2.12-addresses-not-populated",
                ),
            )

        report.log(
            "2.12 selected pre-existing Debtor after duplicate warning",
            True,
            f"row {exact[0]}",
        )

        return

    dialog.cancel()

    raise ManualReviewRequired(
        "2.11 duplicate Debtor",
        (
            f"a contact matching {d.first_name} {d.last_name} / "
            f"{d.billing.street} that also matches "
            f"Company={d.company!r} "
            f"ZIP={d.billing.zip!r} "
            f"City={d.billing.city!r}"
        ),
        (
            "Fakturama rejected the new Debtor as a duplicate, "
            "and the existing contact(s) do not match the source "
            f"document: {candidates or rows}"
        ),
        _shot(
            app,
            report,
            "2.11-duplicate-debtor-conflict",
        ),
    )


_GEOMETRY_KEYS = ("_cy", "_top", "_bottom", "_x0")


def _carry_geometry(mapped: dict, raw: dict) -> dict:
    for key in _GEOMETRY_KEYS:
        if key in raw:
            mapped[key] = raw[key]
    return mapped


def _row_to_debtor_match(r: dict) -> dict:
    return _carry_geometry({
        "company": r.get("Company", ""),
        "first_name": r.get("First Name", ""),
        "name": r.get("Name", ""),
        "zip": r.get("ZIP", ""),
        "city": r.get("City", ""),
    }, r)


def _row_to_product_match(r: dict) -> dict:
    return _carry_geometry({"item_no": r.get("Item No.", "")}, r)


def _search_product(
    sku: str, editor: "pages.OrderEditor"
) -> tuple["pages.ProductSelectDialog", "D.Decision"]:
    dialog = editor.open_product_selector()

    if not dialog.search(sku):
        return dialog, D.Decision(
            "select",
            reason="the selector confirmed the single filtered row and closed")

    rows = dialog.rows_stable()
    decision = D.match_product([_row_to_product_match(r) for r in rows], sku)
    if decision.action == "create":
        decision.reason = f"no exact SKU {sku!r} among {_visible(rows)}"
    return dialog, decision


def _debtor_combination_key(d) -> str:
    a = d.billing
    parts = (d.first_name, d.last_name, d.company, a.zip, a.city)
    return " ".join(p.strip() for p in parts if (p or "").strip())


def _debtor_search_terms(d) -> list[str]:
    terms = [_debtor_combination_key(d), ""]
    return [t for i, t in enumerate(terms) if t not in terms[:i]]


def _search_existing_debtor(
    editor: "pages.OrderEditor", d
) -> tuple["D.Decision", list[str], "pages.AddressSelectDialog"]:
    attempts: list[str] = []
    last = D.Decision("create")
    dialog = editor.open_address_selector()

    for index, term in enumerate(_debtor_search_terms(d)):
        if index:
            dialog.cancel()
            dialog = editor.open_address_selector()

        dialog.search(term)
        rows = dialog.rows_stable()

        decision = D.match_debtor(
            [_row_to_debtor_match(r) for r in rows],
            d.company,
            d.first_name,
            d.last_name,
            d.billing.zip,
            d.billing.city,
        )

        attempts.append(
            f"{term!r}->{len(rows)} row(s)/{decision.action}"
        )
        last = decision

        if decision.action in ("select", "review"):
            return decision, attempts, dialog

    return last, attempts, dialog


def seed_payment_methods(
    app: App,
    report: RunReport,
) -> dict[str, str]:
    pm = pages.PaymentMethodEditor(app)

    try:
        pm.open_list()
    except Exception as e:
        raise ManualReviewRequired(
            "2.10.1 terms of payment",
            "the terms of payment list",
            f"Could not open it: {e}",
            _shot(app, report, "seed-payment-browser-failure"),
        ) from e

    outcomes: dict[str, str] = {}

    for method, code in D.PAYMENT_CODE_MAP.items():
        try:
            pm.open_list()
            rows = pm.rows()
        except Exception as e:
            raise ManualReviewRequired(
                "2.10.2 payment method lookup",
                method,
                f"Could not read terms of payment: {e}",
                _shot(app, report, "seed-payment-browser-failure"),
            ) from e

        decision = D.match_payment_method(
            [{"name": r.get("Name", "")} for r in rows],
            method,
        )

        if decision.action == "review":
            raise ManualReviewRequired(
                "2.10.2 payment method lookup",
                f"0 or 1 rows named {method}",
                decision.reason,
                _shot(app, report, f"seed-payment-ambiguous-{code}"),
            )

        if decision.action == "select":
            outcomes[method] = "existed"
            report.log(f"seed: {method} already exists", True)
            continue

        pm.create(method, code)
        report.note_created("payment_method", method)
        outcomes[method] = "created"
        report.log(f"seed: created {method}", True, f"payment code {code!r}")

    report.log(
        "seed payment methods (2.10.4 mapping)",
        True,
        ", ".join(f"{m}={o}" for m, o in outcomes.items()),
    )
    return outcomes


def _resolve_and_add_item(
    order: OrderData,
    item,
    app: App,
    editor: "pages.OrderEditor",
    report: RunReport,
    running: "RunningTotals",
) -> None:
    # 3.2 Open Product selector from SAME New Order

    dialog, decision = _search_product(item.sku, editor)

    # Ambiguous product

    if decision.action == "review":
        raise ManualReviewRequired(
            f"3.3 Product match ({item.sku})",
            "exactly one exact SKU match",
            decision.reason,
            _shot(
                app,
                report,
                f"3.3-product-ambiguous-{item.sku}",
            ),
        )

    # Product doesn't exist -> create

    if decision.action == "create":
        dialog.cancel()

        vat_name = _ensure_vat(
            item.vat_pct,
            app,
            report,
        )

        pe = pages.ProductEditor.open_new(app)

        pe.fill(
            item.sku,
            item.description,
            item.product_gross_price,
            vat_name,
        )

        saved = pe.save(
            item.sku,
            name=item.description,
            vat_name=vat_name,
            price_gross=item.product_gross_price,
        )

        report.note_created(
            "product",
            item.sku,
        )

        report.log(
            f"3.4-3.11 create Product {item.sku}",
            True,
            f"gross {item.product_gross_price} = {item.unit_net} x "
            f"(1 + {item.vat_pct}/100); saved as {saved}",
        )

        # Return to SAME New Order and reselect Product

        dialog, decision = _search_product(item.sku, editor)

        if decision.action != "select":
            raise ManualReviewRequired(
                "3.12 reselect new Product",
                item.sku,
                f"{decision.action}: {decision.reason}",
                _shot(
                    app,
                    report,
                    f"3.12-new-product-not-found-{item.sku}",
                ),
            )

    # Select Product

    if dialog.self_confirmed:
        report.log(
            f"3.2-3.12 select Product {item.sku}",
            True,
            "the selector confirmed the single filtered row and closed itself",
        )
    else:
        dialog.select_row(decision.row)
        dialog.ok()

        report.log(
            f"3.2-3.12 select Product {item.sku}",
            True,
        )

    row = editor.find_item_row(item.sku)

    if row is None:
        raise ManualReviewRequired(
            f"3.12 Product line for {item.sku}",
            f"an Items row showing {item.sku}",
            f"the Items table shows {_visible(editor.read_item_rows(item.sku))}",
            _shot(app, report, f"3.12-no-line-{item.sku}"),
        )

    editor.set_current_line(
        item.quantity,
        item.unit_net,
        item.discount_pct,
        sku=item.sku,
    )

    # 3.14-3.16
    running.add(item)
    detail = _verify_line(item, running, app, editor, report)

    report.log(
        f"3.13-3.16 complete line {item.sku}",
        True,
        (
            f"qty={item.quantity} "
            f"price={item.unit_net} "
            f"disc={item.discount_pct}% "
            f"vat={item.vat_pct}% "
            f"line_net={item.computed_line_net}; {detail}"
        ),
    )


def _visible(rows: list[dict]) -> list[dict]:
    """Grid rows without grid_ocr's private geometry keys, for error messages."""
    return [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows]


class RunningTotals:
    def __init__(self) -> None:
        self.net = Decimal("0.00")
        self.vat = Decimal("0.00")

    def add(self, item) -> None:
        from ..models import cents

        line_net = item.computed_line_net
        self.net += line_net
        self.vat += cents(line_net * item.vat_pct / 100)


def _verify_line(
    item,
    running: RunningTotals,
    app: App,
    editor: "pages.OrderEditor",
    report: RunReport,
) -> str:
    def _totals() -> tuple[Optional[Decimal], Optional[Decimal]]:
        net, vat, _gross = editor.totals()
        return D.parse_number(net), D.parse_number(vat)

    try:
        wait_until(lambda: _totals() == (running.net, running.vat),
                   f"Order totals to reach net={running.net} vat={running.vat}",
                   timeout=10, interval=0.5)
    except Exception as exc:
        raise ManualReviewRequired(
            f"3.16 verify line {item.sku}",
            (
                f"Order Total Net {running.net} / VAT {running.vat} after a line of "
                f"qty={item.quantity} x {item.unit_net} "
                f"less {item.discount_pct}% at {item.vat_pct}% VAT"
            ),
            (
                f"totals read {_totals()}; Items table shows "
                f"{_visible(editor.read_item_rows(item.sku))}"
            ),
            _shot(app, report, f"3.16-line-mismatch-{item.sku}"),
        ) from exc

    row = editor.find_item_row(item.sku)
    grid = D.match_order_line(
        row, item.quantity, item.unit_net, item.discount_pct,
        item.vat_pct, item.computed_line_net,
    ) if row is not None else D.Decision("review", reason="row not readable")

    return (f"Order totals now net={running.net} vat={running.vat}; "
            f"grid read {grid.action}: {grid.reason}")


def _ensure_vat(
    vat_pct: Decimal,
    app: App,
    report: RunReport,
) -> str:
    ve = pages.VatEditor(app)

    # 3.5 VAT browser lookup

    try:
        ve.open_list()
        rows = ve.rows()

    except Exception as e:
        raise ManualReviewRequired(
            "3.5 VAT lookup",
            f"VAT {D.fmt_pct(vat_pct)}%",
            f"Could not access VAT Data Browser: {e}",
            _shot(
                app,
                report,
                "3.5-vat-browser-failure",
            ),
        ) from e

    # Match VAT

    decision = D.match_vat(
        [
            {
                "name": r.get("Name", ""),

                "value": r.get("Value", ""),

                "code": None,
            }
            for r in rows
        ],
        vat_pct,
    )

    name = f"VAT {D.fmt_pct(vat_pct)}%"

    # Ambiguous VAT

    if decision.action == "review":
        raise ManualReviewRequired(
            "3.5 VAT match",
            name,
            decision.reason,
            _shot(
                app,
                report,
                "3.5-vat-ambiguous",
            ),
        )

    # Existing VAT

    if decision.action == "select":
        report.log(
            f"3.4-3.5 reuse VAT {name}",
            True,
        )
        return name

    # Create VAT

    ve.create(
        name,
        vat_pct,
    )

    report.note_created(
        "vat",
        name,
    )

    report.log(
        f"3.6 create VAT {name}",
        True,
    )

    return name
