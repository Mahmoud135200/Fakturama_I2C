# Mock orders

Run them **in this order** against a fresh Fakturama: later scenarios rely on master data created by earlier ones (existing-Debtor, existing-Product and existing-VAT branches).

| File | Cust.Ref. | What it exercises | Expected outcome |
|---|---|---|---|
| order_01_new_debtor_paid.png | WEB-2026-0714-A17 | Original sample. New Debtor (2 addresses), new payment method Bank Transfer, new VAT 19%, 2 new Products. PAID. | completes |
| order_02_existing_debtor_unpaid.png | WEB-2026-0802-B03 | Existing Debtor (Northstar, exact 5-field match), existing Product CHR-ERG-01 + new LMP-LED-07, new payment method Credit Card on the Invoice only. UNPAID. VAT total hits a half-cent (70.965). | completes |
| order_03_same_address_vat7.png | WEB-2026-0815-C11 | New Debtor whose billing == delivery (one address, both roles), new VAT 7%, new payment method SEPA Direct Debit. PAID. | completes |
| order_04_three_items_mixed_vat.png | WEB-2026-0901-D42 | New Debtor, 3 new Products, mixed VAT (19% + existing 7%), 5%/15% discounts. UNPAID. | completes |
| order_05_photo_noisy.jpg | WEB-2026-0910-E05 | Phone-photo style image (rotation, blur, JPEG, uneven light). Existing Debtor Hafenblick and existing Products only — nothing should be created. PAID. | completes |
| order_06_bad_line_total.png | WEB-2026-0915-F99 | NEGATIVE: item 1 prints a line total that does not equal qty x price x (1-disc). Extraction validation must stop the run before Fakturama is touched. | stops at validation |
