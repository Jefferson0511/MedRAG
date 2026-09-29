# Corpus sources

Raw files live in `data/raw/` and are gitignored (copyrighted guideline content is
not redistributed). This file is the record of exactly what is in the corpus, where
it came from, and when it was accessed, so the corpus can be rebuilt and every
expected eval answer can be traced back to a real document.

## Source log

Add a row every time a file is saved. Fill it in as you go, not at the end.

| File | Source org | Title | URL | Accessed | Text-selectable? | Eval Qs covered |
|---|---|---|---|---|---|---|
| cdc/cdc_hearher_warning_signs.pdf | CDC | Urgent Maternal Warning Signs | https://www.cdc.gov/hearher/maternal-warning-signs/index.html | 2026-09-28 | yes | Q2, Q9, Q10, Q11, Q12 |
| cdc/cdc_folic_acid.pdf | CDC | About Folic Acid | https://www.cdc.gov/folic-acid/about/index.html | 2026-09-28 | yes | Q1 |
| cdc/cdc_gestational_diabetes.pdf | CDC | Gestational Diabetes | https://www.cdc.gov/diabetes/about/gestational-diabetes.html | 2026-09-28 | yes | Q19 |
| cdc/cdc_postpartum_depression.pdf | CDC | Symptoms of Depression Among Women | https://www.cdc.gov/reproductive-health/depression/index.html | 2026-09-28 | yes | Q8 |
| acog/acog_preeclampsia.pdf | ACOG | Preeclampsia and High Blood Pressure During Pregnancy | https://www.acog.org/womens-health/faqs/preeclampsia-and-high-blood-pressure-during-pregnancy | 2026-09-28 | yes | Q6 |
| acog/acog_chap_practice_advisory.pdf | ACOG | Clinical Guidance for the Integration of the Findings of the CHAP Study (Practice Advisory, Apr 2022, reaffirmed Mar 2025) | https://www.acog.org/clinical/clinical-guidance/practice-advisory/articles/2022/04/clinical-guidance-for-the-integration-of-the-findings-of-the-chronic-hypertension-and-pregnancy-chap-study | 2026-09-28 | yes | Q7 |
| acog/acog_prenatal_care.pdf | ACOG | Prenatal Care | https://www.acog.org/womens-health/faqs/prenatal-care | 2026-09-28 | yes | Q4 |
| acog/acog_pregestational_diabetes.pdf | ACOG | Pregnancy With Type 1 or Type 2 Diabetes | https://www.acog.org/womens-health/faqs/pregnancy-with-type-1-or-type-2-diabetes | 2026-09-28 | yes | Q5 |
| acog/acog_gestational_diabetes.pdf | ACOG | Gestational Diabetes | https://www.acog.org/womens-health/faqs/gestational-diabetes | 2026-09-28 | yes | Q19 |
| acog/acog_postpartum_depression.pdf | ACOG | Postpartum Depression | https://www.acog.org/womens-health/faqs/postpartum-depression | 2026-09-28 | yes | Q8 |
| lactmed/lactmed_ibuprofen.pdf | NLM (LactMed) | Ibuprofen (revised 2025-08-15) | https://www.ncbi.nlm.nih.gov/books/NBK500986/pdf/Bookshelf_NBK500986.pdf | 2026-09-29 | yes | Q3 |
| lactmed/lactmed_sertraline.pdf | NLM (LactMed) | Sertraline (revised 2026-08-15) | https://www.ncbi.nlm.nih.gov/books/NBK501191/pdf/Bookshelf_NBK501191.pdf | 2026-09-29 | yes | none (supporting corpus / retrieval distractor) |

## Held out (not in the static corpus)

Collected and kept locally in `data/holdout/` (gitignored), but deliberately NOT
ingested. These exist so a live-tool answer can be checked against a document
that has actually been read.

| File | Source org | Title | URL | Accessed | Text-selectable? | Eval Qs covered |
|---|---|---|---|---|---|---|
| holdout/lactmed/lactmed_acetaminophen.pdf | NLM (LactMed) | Acetaminophen (revised 2026-04-15) | https://www.ncbi.nlm.nih.gov/books/NBK501194/pdf/Bookshelf_NBK501194.pdf | 2026-09-29 | yes | Q18 (reference for checking the live LactMed tool's answer) |

## Eval coverage matrix

Every answerable question needs at least one source. Q13-Q15 must have NONE,
their absence from the corpus is what makes them valid refusal tests.

| Q | Category | Covered by | Status |
|---|---|---|---|
| Q1 | Factual | cdc/cdc_folic_acid.pdf | Source collected |
| Q2 | Factual | cdc/cdc_hearher_warning_signs.pdf (page says "heavy bleeding", never "hemorrhage": semantic-match test) | Source collected |
| Q3 | Factual | lactmed/lactmed_ibuprofen.pdf | Source collected |
| Q4 | Factual | acog/acog_prenatal_care.pdf | Source collected |
| Q5 | Comorbidity | acog/acog_pregestational_diabetes.pdf | Source collected |
| Q6 | Comorbidity | acog/acog_preeclampsia.pdf | Source collected |
| Q7 | Comorbidity | acog/acog_chap_practice_advisory.pdf | Source collected |
| Q8 | Comorbidity | acog/acog_postpartum_depression.pdf, cdc/cdc_postpartum_depression.pdf | Source collected |
| Q9 | Escalation | cdc/cdc_hearher_warning_signs.pdf (headache; changes in vision) | Source collected |
| Q10 | Escalation | cdc/cdc_hearher_warning_signs.pdf (baby's movement stopping or slowing) | Source collected |
| Q11 | Escalation | cdc/cdc_hearher_warning_signs.pdf (vaginal bleeding after pregnancy) | Source collected |
| Q12 | Escalation (control) | cdc/cdc_hearher_warning_signs.pdf (near-miss: "Overwhelming tiredness" is defined as sudden and severe, which Q12 is not) | Source collected |
| Q13 | Unanswerable | Intentionally none | n/a |
| Q14 | Unanswerable | Intentionally none | n/a |
| Q15 | Unanswerable | Intentionally none | n/a |
| Q16 | Tool-call | Live lookup, not static corpus | Week 4 |
| Q17 | Tool-call | Live PubMed lookup, not static corpus | Week 4 |
| Q18 | Tool-call | Live LactMed lookup; held-out holdout/lactmed/lactmed_acetaminophen.pdf is the answer check | Week 4 |
| Q19 | Multi-source | acog/acog_gestational_diabetes.pdf, cdc/cdc_gestational_diabetes.pdf | Source collected |
| Q20 | Multi-source | ACOG corpus + live PubMed lookup | Week 4 |

"Source collected" means a matching file is in the corpus. It does not mean an
expected answer has been written and checked against that file yet.

## Not accessible

Anything behind a login or paywall that was needed but couldn't be collected,
and what was used instead.

| Wanted | Why not accessible | Substitute used |
|---|---|---|
| ACOG Practice Bulletin No. 203, Chronic Hypertension in Pregnancy (2019), for specific medication names | Not collected; likely members-only | Q7 rewritten around the CHAP Practice Advisory's treatment threshold instead |