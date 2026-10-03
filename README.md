# Fakturama Image-to-Cash — Design

The goal of the system is to take an order image or PDF and turn it into a correctly created and verified **Order and Invoice** inside Fakturama.

The system is divided into three clear stages:

```text
Order Image / PDF
       ↓
   [1. Extract]
       ↓
 Validated OrderData
       ↓
    [2. Plan]
       ↓
 Business decisions
       ↓
   [3. Execute]
       ↓
   Fakturama UI
       ↓
    RunReport
```

Each stage has a clear responsibility:

* **Extract** understands the document and produces structured data.
* **Plan** decides what should be created and what can be reused.
* **Execute** performs the operations inside Fakturama and verifies them.

The stages are intentionally separated. Extraction never interacts with the Fakturama UI, and UI automation never reads the original document. Their only connection is the validated `OrderData`.

The main execution rule is:

```text
Act → Wait → Verify → Continue
```

The system never assumes that an action succeeded. If the expected state does not appear, the run stops and produces a manual-review result with the reason and supporting evidence.

---

## 1. Image Extraction and Validation

The first stage turns the order image or PDF into structured and validated data.

Windows' built-in OCR engine reads the text and its position on the page. The system then uses labels and table headers to understand what each value represents.

```text
Order Image / PDF
       ↓
  Windows OCR
       ↓
Find labels and table columns
       ↓
 Normalize values
       ↓
Validate data and calculations
       ↓
    OrderData
```

The OCR runs locally, so no document data leaves the machine.

### Example

Suppose the document contains:

```text
EXTERNAL REFERENCE: WEB-2026-0714-A17
ORDER DATE: 2026-07-14

SKU        Qty    Unit net    Disc.    VAT
BOOK-001    2      50.00       10%      19%

Net total: 90.00
VAT:       17.10
Gross:    107.10
```

The parser produces structured data such as:

```json
{
  "external_reference": "WEB-2026-0714-A17",
  "order_date": "2026-07-14",
  "items": [
    {
      "sku": "BOOK-001",
      "quantity": 2,
      "unit_net": "50.00",
      "discount": "10",
      "vat": "19",
      "line_net": "90.00"
    }
  ],
  "net_total": "90.00",
  "vat_total": "17.10",
  "gross_total": "107.10"
}
```

The system validates required fields and checks the document's calculations:

```text
quantity × unit_net × (1 - discount / 100) = line_net

Σ line_net = net_total

net_total + vat_total = gross_total
```

If OCR misses a small value such as `10%` or `2`, that specific region can be re-read at a higher resolution.

Only data that passes validation becomes `OrderData`.

> **The extraction stage never interacts with Fakturama.**

---

## 2. Fakturama UI Automation

The second stage interacts with Fakturama.

The automation primarily uses **Windows UI Automation (UIA)** rather than fixed screen coordinates.

For example, instead of:

```text
Click X=720, Y=350
```

the system looks for:

```text
Button named "OK"
```

This makes the automation more stable when the window moves or the screen resolution/display scaling changes.

The lookup strategy is:

1. UIA semantic lookup
2. Label-relative lookup
3. Toolbar/tooltip names
4. Region OCR for opaque controls
5. Mouse interaction only where UIA cannot operate

For example, for a Date field, the system looks for the Date label and its associated input instead of assuming a fixed position.

### NatTable grids

Fakturama's NatTable grids expose very little useful information through UIA.

For these tables, the system:

1. Gets the grid's UIA bounding rectangle.
2. Captures only that region.
3. Runs OCR on the region.
4. Uses the OCR result to understand rows and columns.

Therefore, OCR is used to **read the state of the table**, while UIA is still used to identify the application region and available controls.

---

## 3. Safe Interaction and Waiting

The automation does not rely on arbitrary delays such as:

```python
sleep(2)
```

Instead, every important action waits for a meaningful condition.

For example:

```text
Click "Select Address"
        ↓
Wait for "Select the address" dialog
        ↓
Verify dialog
        ↓
Continue
```

After entering a value, the system also reads it back.

For example:

```text
Write: 250.00
Read: 250,00 €
       ↓
   Normalize
       ↓
Both represent 250.00
       ↓
      Pass
```

If direct UIA value entry does not work, the system falls back to keyboard input:

```text
Focus → Ctrl+A → Type → Tab → Read back
```

This is particularly useful for Fakturama's locale-dependent number and date formatting.

---

## 4. Page Objects

Each Fakturama screen has its own page object containing the rules needed to interact with that screen.

Examples include:

```text
OrderEditor
AddressSelectDialog
ProductSelectDialog
DebtorEditor
PaymentMethodEditor
VatEditor
ProductEditor
DocumentsView
InvoiceEditor
```

The main workflow can therefore focus on the business process rather than UIA implementation details:

```text
Open Order
    ↓
Select Debtor
    ↓
Select Products
    ↓
Set Payment Method
    ↓
Set VAT
    ↓
Verify Totals
    ↓
Save
    ↓
Create Invoice
    ↓
Verify Invoice
```

The page objects handle the actual UI discovery and interaction behind these steps.

---

## 5. Business Decisions

Before creating master data, the system checks whether it already exists in Fakturama.

This prevents unnecessary duplicates.

| Data           | Matching rule                                | Result                                                 |
| -------------- | -------------------------------------------- | ------------------------------------------------------ |
| Debtor         | Company, first name, last name, ZIP and city | One → reuse, none → create, multiple/conflict → review |
| Payment method | Exact name                                   | One → reuse, none → create, conflict → review          |
| VAT            | Name + percentage + code                     | One → reuse, none → create, conflict → review          |
| Product        | Exact SKU / Item Number                      | One → reuse, none → create, multiple → review          |
| Totals         | Fakturama totals vs. source totals           | Equal → continue, different → review                   |

### Example

If the source contains:

```text
SKU: BOOK-001
```

the system searches Fakturama for:

```text
Item Number = BOOK-001
```

If exactly one product exists, it is reused.

If none exists, it is created.

If multiple products have the same identifier, the system does not choose between them. It stops for manual review.

The same principle is applied to customers, VAT entries, and payment methods.

---

## 6. Order Creation and Idempotency

The system is designed so that it can safely be restarted after a failure.

Most master-data operations are naturally reusable. For example, if a Payment Method was created before a crash, the next run finds it and reuses it instead of creating another one.

The Order itself requires special handling because saving it creates a new business document.

Before creating the Order, the system searches Fakturama's Documents for an existing Order with the same customer reference.

For example:

```text
Customer Reference:
WEB-2026-0714-A17
```

The logic is:

```text
Search Documents
       ↓
Existing reference?
    /       \
  Yes        No
   ↓          ↓
 Review     Create
```

This prevents the same Order from being created twice after a retry.

---

## 7. Payment and Invoice Handling

After the Order is created, the system creates the linked Invoice and applies the payment information from the source document.

If the source says:

```text
Status: PAID
Payment date: 2026-07-15
```

the Invoice is marked as paid with the correct payment date and amount.

If the source is not marked as paid, the payment information is left unchanged.

Before the Order is saved, Fakturama's calculated totals are compared with the original document:

```text
Fakturama Net   = Source Net
Fakturama VAT   = Source VAT
Fakturama Gross = Source Gross
```

If any value differs, the Order is not saved and the run stops for review.

---

## 8. Verification

Verification happens throughout the process rather than only at the end.

After important values are entered, they are read back and compared with the expected data.

After saving, the system checks Fakturama's Documents view to confirm that the expected Order and Invoice exist.

The Invoice is then reopened to verify:

```text
Payment method
Paid status
Payment date
Payment amount
```

There is also an optional read-only check using Fakturama's embedded HSQLDB.

This provides an additional confirmation that the expected records were persisted. The database is never used to modify data.

---

## 9. Evidence and Run Reports

Every important step produces evidence.

The system records:

* Screenshots
* JSON event logs
* Validation results
* Created document IDs
* Verification results
* Manual-review reasons

A run produces something similar to:

```text
runs/
└── 20261002-184741/
    ├── screenshots/
    ├── events.jsonl
    └── report.json
```

The final report tells us whether the run succeeded or stopped and why.

Example:

```json
{
  "ok": false,
  "error": "Manual review required",
  "step": "select_debtor",
  "reason": "Multiple matching debtors found"
}
```

This makes failures explainable instead of simply reporting that the automation crashed.

---

## 10. Manual Review

Manual review is a normal and intentional outcome.

The system stops whenever it cannot safely make a decision.

There are two main cases:

```text
Invalid / inconsistent document
        ↓
Stop during extraction
```

or:

```text
Valid document but ambiguous Fakturama data
        ↓
Stop during planning/execution
```

The test corpus contains both types of cases.

* `samples/mock/` contains valid orders covering different create/reuse paths.
* `samples/edge/` contains documents that are expected to stop.

A reliable automation system should test not only whether it can complete a task, but also whether it knows when **not to continue**.

---

## 11. Implementation Reality Check

The design was tested against an actual installed **Fakturama 2.2** instance.

Three important findings affected the implementation.

### NatTable

The application's major tables expose very little information through UIA.

Therefore, region OCR is an important part of the implementation rather than just an optional fallback.

### Address and Item Icons

Some icons are graphical SWT elements and do not expose useful UIA actions.

For these specific controls, the system calculates their live position and performs a real mouse interaction.

### Changing Tab Names

Fakturama changes some tab names depending on the currently active screen.

For example:

```text
Fakturama → New Order → New Debtor
```

The Data browser can similarly change between:

```text
Documents → VATs → terms of payment
```

Therefore, these names cannot always be used as permanent anchors. The automation instead uses more stable parent containers and screen-specific lookup rules.

---

## 12. Overall Design

The complete system can be summarized as:

```text
                  ORDER IMAGE / PDF
                         │
                         ▼
                ┌─────────────────┐
                │     Extract     │
                │                 │
                │ OCR             │
                │ Parsing         │
                │ Normalization   │
                │ Validation      │
                └────────┬────────┘
                         │
                         ▼
                    OrderData
                         │
                         ▼
                ┌─────────────────┐
                │      Plan       │
                │                 │
                │ Match / Create  │
                │ Business Rules  │
                │ Duplicate Check │
                └────────┬────────┘
                         │
                         ▼
                ┌─────────────────┐
                │     Execute     │
                │                 │
                │ UI Automation   │
                │ Read-back       │
                │ Verification    │
                └────────┬────────┘
                         │
                         ▼
                ┌─────────────────┐
                │    RunReport    │
                │                 │
                │ Results         │
                │ Evidence        │
                │ Screenshots     │
                │ Review Reason   │
                └─────────────────┘
```

The main principle is:

> **Extract and validate first, make explicit business decisions, interact with Fakturama carefully, verify every important action, and stop whenever the system cannot make a safe decision.**

---

## 13. If I Had 3 More Hours

If I had three more hours, I would focus on **performance, reliability, and reducing the dependency on the foreground window**.

### 1. Improve execution speed

I would profile the flow and reduce unnecessary:

* UIA tree searches
* repeated OCR calls
* waits
* screenshots

Some operations are currently repeated because reliability was prioritized over speed.

### 2. Reduce foreground dependency

The current implementation keeps Fakturama in the foreground because some SWT controls, especially NatTable grids and graphical selector icons, do not expose reliable UIA interaction patterns.

Those controls currently require a real mouse interaction or a screenshot.

With more time, I would investigate whether these interactions can be replaced with keyboard/UIA patterns or isolated into a small foreground-only section, allowing most of the workflow to run without taking control of the user's desktop.

### 3. Add a background mode

I would add an option such as:

```bash
python -m fakturama_i2c run order.png --background
```

The background mode would avoid stealing focus whenever possible and only use foreground interaction for controls that genuinely require it.

### 4. Improve OCR performance

I would cache OCR results and only re-read regions when the initial result fails validation.

This would reduce processing time while keeping the current multi-variant OCR approach for difficult documents.

### 5. Run all mock scenarios end-to-end

I would run all six mock scenarios against a clean Fakturama workspace and fix any remaining live UI issues, especially the unverified inline editing of the Items table.

### Why wasn't this done from the beginning?

The implementation was developed in stages because the first priority was to prove that the automation could **reliably complete the business process and fail safely**.

Fakturama is an SWT application, and some of its controls are not fully exposed through UI Automation. Optimizing for background execution before understanding those limitations could have produced a faster but less reliable system.

The development order was therefore:

```text
Correctness
    ↓
Validation
    ↓
Live UI verification
    ↓
Error handling
    ↓
Performance optimization
    ↓
Background execution
```

After live testing, it became clear which operations can safely run without the foreground and which still require it. This makes background mode an optimization based on the actual behavior of the application rather than an assumption.
