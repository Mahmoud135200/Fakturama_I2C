# Edge cases -- inputs the automation must refuse

Each PNG is a complete order document; the matching
`.expected.json` records what the document says plus why it is an edge case.

## A. Stop at validation (Fakturama is never touched)

`run` extracts and validates BEFORE attaching to Fakturama, so these exit 2
with the problem list and never touch the application -- no Fakturama needed:

```
cd src
python -m fakturama_i2c run ../samples/edge/<file>.png
```

| File | What it prints wrong | Stops at |
|---|---|---|
| edge_01_line_total_wrong.png | Item 1 prints a Line net that is not qty x unit net x (1 - discount). | item line arithmetic |
| edge_02_net_total_wrong.png | Both item lines are self-consistent, but the printed NET TOTAL is 10.00 too high. | sum of lines != NET TOTAL |
| edge_03_vat_total_wrong.png | Lines and NET TOTAL agree, but the printed VAT TOTAL is 5.00 too high. | computed VAT != VAT TOTAL |
| edge_04_gross_total_wrong.png | NET and VAT totals are right, but GROSS TOTAL is 1.00 off (net + vat != gross). | net + VAT != GROSS |
| edge_05_unknown_payment_method.png | Payment method is 'PayPal' -- outside the 2.10.4 mapping, so no payment code can be chosen. | unknown payment method |
| edge_06_paid_without_date.png | Status badge says PAID but the Payment date cell is empty -- 5.3 would have to invent a date. | PAID with no payment date |
| edge_07_debtor_fields_missing.png | Company cell is blank and the contact shows a first name only -- a Debtor cannot be created. | missing debtor company / contact name |
| edge_08_delivery_address_incomplete.png | Delivery address prints a street but no ZIP and no city. | incomplete delivery address |
| edge_09_external_reference_missing.png | External reference cell is blank -- nothing to put in Cust.Ref. (1.6). | missing external reference |

## B. Stop for manual review (needs Fakturama running)

These documents are valid. The ambiguity lives in Fakturama, so do the setup step first,
then run the full flow:

```
cd src
python -m fakturama_i2c run ../samples/edge/<file>.png --out-dir ../runs/<name>
```

Expect the manual-review popup, a non-zero exit, and the reason in `runs/<name>/report.json`.

| File | Setup first | Stops at |
|---|---|---|
| edge_10_duplicate_debtor.png | Run samples/mock/order_01_new_debtor_paid.png first so the real Northstar contact exists. | 2.11 duplicate Debtor |
| edge_11_conflicting_vat.png | In Fakturama: Data > VATs > green +, Name AND Description 'VAT 21%', Value 20%, save. | 3.5 VAT match |
| edge_12_ambiguous_product.png | In Fakturama: New product with Item Number CHR-ERG-01 (any name/price), save -- so two products share that SKU. | 3.3 Product match |
| edge_13_ambiguous_payment_method.png | In Fakturama: Data > terms of payment > green +, Name 'Credit Card', save -- repeat until exactly two identically named rows exist. | 2.10.2 payment method lookup |
