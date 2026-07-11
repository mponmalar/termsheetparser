# User Guide — Sales Team

Open the app in your browser (your desk will share the URL; locally it is
http://localhost:8000).

## The screen at a glance

* **Top bar** — running totals: term sheets processed, extractions, lessons
  the agents have learned, a field-accuracy indicator, and the LLM mode
  (`BEDROCK` in production, `MOCK` in offline testing).
* **Left rail** — the upload box, the **blotter** (every uploaded term sheet
  with its status), and *What the agents learned* (recent lessons).
* **Main pane** — the review ledger for the selected term sheet.

## 1. Upload a term sheet

Drag the PDF or Word file you received from the counterparty into the upload
box (or click *browse*). Accepted: `.pdf`, `.docx`, `.doc`, `.txt`.

The agents immediately: parse the document, **mask the counterparty name and
all contact/account details before anything is sent to the LLM**, recall
lessons from past corrections, extract the trade economics, and review their
own work. This takes a few seconds; the blotter entry flips from
*PROCESSING* to *PENDING REVIEW*.

## 2. Review the extraction

Click the document in the blotter. The ledger shows every field grouped as
Identification, Dates, Economics, Underlyings, Barriers & autocall, and
Settlement & legal. Next to each value a chip tells you where it came from:

* **LLM** — extracted by the model this run.
* **LESSON** — the agents applied a correction learned from a previous
  manual edit (yours or a colleague's).
* **EDITED** — manually corrected on this document.

Below the ledger:

* **Agent conversation** — the step-by-step trail, including any issues the
  CriticAgent raised and how many extraction passes were needed.
* **Masked source sent to the LLM** — exactly what left the box, with every
  masked item highlighted. Use this to verify no sensitive data escaped.

## 3. Correct a field (this trains the agents)

Click into any value and type the correction. Dates are `YYYY-MM-DD`;
percentages are plain numbers (`80` for 80%). Underlyings can be edited via
*Edit underlyings as JSON* under the table.

Edited fields turn amber; press **Save**. Two things happen:

1. The value is corrected on this trade.
2. A **lesson** is recorded. On the next similar term sheet the agents apply
   it automatically — you'll see the field arrive with a **LESSON** chip.

You can prove it immediately: after saving, press **Re-run agents** on the
same document and watch the corrected value come back on its own.

## 4. Approve

When the ledger is right, press **Approve → queue for Murex**. The
extraction locks (no further edits), the trade payload is generated and
queued for Murex publication, and the payload is shown for your records.

If you approve by mistake, contact middle office — approval is deliberately
irreversible in the GUI.

## 5. Statuses

| Status | Meaning |
|---|---|
| PROCESSING | Agents are working on the document |
| PENDING REVIEW | Extraction ready — review, edit, approve |
| APPROVED | Locked and queued for Murex |
| FAILED | Parsing/pipeline error — check the agent trail, re-upload if needed |

## Tips

* The more you correct, the less you will need to: lessons are shared across
  the desk and ranked by similarity to each new document.
* If a field is genuinely absent from the term sheet, leave it empty (null)
  rather than guessing — the critic flags truly required gaps.
* The sample files in `samples/` are safe synthetic term sheets for practice.
