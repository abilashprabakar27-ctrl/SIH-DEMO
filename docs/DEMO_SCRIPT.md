# Demo script

Start from a fresh database with `make seed && make run`. Then open http://localhost:8000 and sign in from the account picker (password `Demo@2026`).
`make demos` runs all three demos through the API and prints PASS/FAIL for each step.

For Demo A, keep a second browser window open on the AICTE national register (`aicte.admin@demo.local`). It updates without a reload; the "updated just now" marker shows the time.

## Demo A — ingestion (about 4 minutes)
1. Sign in as **kaveri.staff@demo.local**, open **Upload records**, and point out the Excel template's drop-down lists.
2. Upload `sample_data/demo_A_kaveri_upload_2026-27.csv`, or the `.xlsx`. The preview shows **5 valid, 2 review, 9 errors**, and every finding says how to fix it.
3. Fix the rows. On the **Error** tab:
   - **Sanjana Balaji** (row 9): APAAR `911100000098` is not found (SIMULATED). The suggestion "Did you mean 911100000008?" matches her name and date of birth. Click **Use this**.
   - **Arun Prakash:** edit the row and set APAAR `911100000006`.
   - **Nandini Raghavan:** the ID has 11 digits; set `911100000007`.
   - **Harini Gopal:** the date of birth 2028-06-18 is in the future; set `2008-06-18`.
   - **Rakesh Iyengar:** an Indian national on an FN/OCI seat; set the seat to `REGULAR`.
   - **Aishwarya Ramesh:** unknown programme `MTECH-AI`; set `MTECH-CSE`. You can also show **Fix the same problem in every row**, the bulk fix.
   - **Pavithra Senthil:** gender `X`; set `F`.
   - **Riya Krishnan** appears twice with the same APAAR. Click **Leave out** on the second row and the first becomes valid.
4. The projection panel shows BTECH-ECE reaching exactly 60/60, within capacity. Click **Commit 15 rows**; the dialog states the counts.
5. In the AICTE window, the figures change live. In the **Review queue**, R007 is open for Vignesh (the registry spells the name "Subramanian") and R004 for Tomas Herrera (foreign national, APAAR pending).

## Demo B — conflict and excess (about 5 minutes)
1. Sign in as **godavari.admin@demo.local** and open **Seat check**. Choose BTECH-CSE, REGULAR, 1. The answer is "This would exceed approved intake by 1 (120 of 120…)".
2. Upload `sample_data/demo_B_godavari_upload_2026-27.csv`. The projection shows **+4 within intake** and the red line "Committing will exceed approved capacity. Records are still accepted and AICTE is flagged."
   - Row 4 is a Kaveri BTECH-ECE student whose name is slightly misspelt. It raises D003 (active elsewhere), D004 (the master record is not overwritten) and R007.
3. Commit 5 rows. Flags open: **C001 (+4)**, **C002 (TFW 7/6)**, **D003** and **D004**.
4. As Godavari, open the D003 flag. The other side reads "Another AICTE-approved institution (identity withheld)" and shows only status and year.
5. As **aicte.admin@demo.local**, open the same flag: both institutions are visible. Click **Request clarification** and add a note.
6. As **kaveri.admin@demo.local**, open the student's record from the flag and click **Change status**. Choose TRANSFERRED_OUT and give a reason.
7. As Godavari, open the flag and **Send response**. Then, as AICTE, **Resolve flag** with a note.
8. As Godavari, cancel 4 admissions using **Change status → CANCELLED** with the reason "Duplicate provisional admission". Use GEC26CSE901–903 plus one other regular admission. (Alternatively, AICTE can resolve C001 with a note.)
   - C001 closes with a logged **SYSTEM_AUTO_RESOLVED** event, and AICTE can reopen it.
   - The word "fraud" appears nowhere.

## Demo C — verification (about 4 minutes)
1. As **kaveri.admin@demo.local**, search Records for "Ananya Iyer", open her record, and click **Issue signed record**. This supersedes the seeded one.
   - **Open certificate** shows the APAAR ID next to the institution student ID, a QR code, and the watermark "SAMPLE · SYNTHETIC DATA".
2. As **student.ananya@demo.local**, open **My record → Share a signed record**. Tick only institution, programme and enrolment status, then click **Create share token**. A QR code and a token appear.
3. Sign out and use **Verify a record without signing in**. Paste the token. All six checks are green; only the three shared claims appear, and the APAAR ID is masked (`XXXX-XXXX-0001`).
4. Click **Demo: tamper with this record (edit a value)**. The digest check fails. "Tamper with the signed part" fails the signature check instead.
5. As Kaveri admin, click **Revoke record** with a reason. Verifying again shows "Revoked on … : reason".
6. As **verifier@demo.local**, open **Request verification**. Enter Ananya's APAAR ID and date of birth (shown on her My record page) and a purpose.
   - The response is the same whether or not the details match. **View result** returns "not given consent" (HTTP 403).
7. As the student, a request is waiting. **Review request** lists exactly which fields will be shared. Click **Allow**. The verifier now sees name, masked APAAR, institution, programme, year and status, and nothing else.
8. As **godavari.staff@demo.local**, try to open Ananya's record URL. You get "Not found" (404 — its existence isn't disclosed).
9. As the student, send a correction request. As **kaveri.staff@demo.local**, it appears under **Correction requests** with a due date. **Accept** opens the correction form pre-filled.
