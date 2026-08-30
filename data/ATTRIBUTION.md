# Data Sources & Attribution

Vigilux Sentinel's `regional_survey_data.csv` combines real, licensed public
health data with fully synthetic data. This file documents which rows are which
per the `data_source` column ("real" vs "synthetic"), satisfying the licensing
disclosure required for any redistributed/brought-in data in an Apache 2.0
submission.

This file covers ONLY the disease/survey data in `regional_survey_data.csv`.
77 of the 94 survey rows are "real" and redistributed under the licenses below;
the remaining 17 rows are "synthetic" and carry no third-party data.

## Real data (licensed, redistributed with attribution)

### COVID-19
Edouard Mathieu, Hannah Ritchie, Lucas Rodés-Guirao, Cameron Appel, Daniel Gavrilov,
Charlie Giattino, Joe Hasell, Bobbie Macdonald, Saloni Dattani, Diana Beltekian,
Esteban Ortiz-Ospina, and Max Roser (2020) – "COVID-19 Pandemic". Data adapted from
World Health Organization. Retrieved from Our World in Data
(https://ourworldindata.org/coronavirus). **Licensed under CC BY 4.0.**

### Tuberculosis
Global Tuberculosis Report 2025. Geneva: World Health Organization; 2025.
Data adapted via Our World in Data
(https://ourworldindata.org/grapher/number-of-tuberculosis-cases).
**Licensed under CC BY 4.0.**

### Malaria (case-count indicator only)
World Health Organization (Global Health Observatory), via World Bank (2026) –
processed by Our World in Data. "New cases of malaria per 1,000 people at risk"
[dataset]. Retrieved from
https://ourworldindata.org/grapher/incidence-of-malaria. **Licensed under CC BY 4.0.**

Note: only this specific case-count indicator was used. OWID's malaria
*deaths* and *prevalence* indicators are sourced from IHME's Global Burden
of Disease study, which is explicitly marked non-redistributable — those
were deliberately excluded.

### Influenza
World Health Organization. FluNet (Global Influenza Virological Surveillance).
Data provided by National Influenza Centres (NICs) of the Global Influenza
Surveillance and Response System (GISRS). https://www.who.int/tools/flunet
Used under the WHO Policy on the Use and Sharing of Data (non-commercial,
not-for-profit use).

## Synthetic data (not derived from any redistributed real dataset)

The remaining 17 survey rows are fully synthetic (HIV, Ebola, and Lassa fever)
and are not derived from, copied from, or redistributing any real dataset.
They are included either because the underlying real indicator sources are
explicitly non-redistributable (IHME Global Burden of Disease, in the case of
HIV) or for narrative grounding only.