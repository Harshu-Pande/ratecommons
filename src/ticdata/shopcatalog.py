"""CareCompass procedure catalog: plain-English procedures, the billing codes behind them, and who may plausibly
perform each part. The descriptions are our own words (CPT descriptor text is licensed and never used).

Each procedure has:
  id, name, short, cat, keywords, about, time, note
  kind: "imaging"   one code; total = global rate, or technical (TC) + reading (26) when billed apart
        "visit"     one code per patient type (new / returning); flat per-visit contracts can stand in
        "service"   one or more codes priced as they are
  codes: the billing codes (imaging: exactly one)
  who:  role -> taxonomy groups qualified to bill that part ("global", "tc", "pro" for imaging; "any" otherwise)
  peds: True when children's hospitals and pediatric clinicians should be offered first for children
"""
from __future__ import annotations

# NUCC taxonomy groups: code prefixes (a provider qualifies when any of its taxonomy codes starts with one)
TAX = {
    "radiology": ["2085"],                                        # radiologists (diagnostic, pediatric, nuclear...)
    "imaging_site": ["261QR0200X", "261QM1200X", "261QR0206X", "261QR0207X", "261QR0208X", "261QX0200X",
                     "282N", "283X", "261QE0700X", "261QH0700X", "261QR0400X", "2085"],
    "hospital": ["282N", "283X", "284300000X", "286500000X", "287300000X"],
    "primary": ["207Q", "207R", "208D", "2080", "363L", "363A", "261QU0200X", "261QP2300X", "261QF0400X",
                "261QR1300X", "261QM1300X", "207P", "261QC1500X", "261QM1000X"],
    "urgent": ["261QU0200X", "207P", "207Q", "207R", "208D", "2080", "363L", "363A", "261QM1300X", "261QP2300X"],
    "ortho": ["207X", "2081", "213E", "261QM1300X"],
    "obgyn": ["207V", "363LW0102X", "363LX0001X", "176B00000X"],
    "cardio": ["207RC", "207RI0011X", "261QM1300X"],
    "psych_md": ["2084P", "2084B0040X", "2084F0202X", "363LP0808X", "261QM0801X", "261QM0850X", "2080P0006X"],
    "therapist": ["103T", "1041C0700X", "101Y", "106H00000X", "2084P", "363LP0808X", "261QM0801X", "103G"],
    "lab": ["291U00000X", "261QM1300X", "207Q", "207R", "208D", "2080", "282N", "261QF0400X", "246Q00000X"],
    "pt": ["2251", "261QP2000X", "225X", "2081P"],
    "gi": ["207RG0100X", "208600000X", "261QA1903X", "282N"],
    "anesthesia": ["207L", "367500000X"],
    "neuro": ["2084N", "2084P", "261QM0801X"],
    "sleep": ["2084S", "207RS0012X", "261QS1200X", "261QM1300X", "207RP1001X"],
}

IMAGING = [
    # code, id, name, short, modality, body, keywords, about, time, extra-sites
    ("70450", "ct-head", "CT scan of the head (no contrast)", "Head CT", "CT", "Head",
     "ct cat head brain scan concussion injury bleeding fall child",
     "A fast X-ray based scan of the head, often after a head injury or a sudden severe headache.", "5–10 min"),
    ("70486", "ct-sinus", "CT scan of the sinuses (no contrast)", "Sinus CT", "CT", "Head",
     "ct sinus sinusitis face", "A CT of the sinuses, usually for long-lasting sinus infections or before sinus surgery.",
     "5–10 min"),
    ("71250", "ct-chest", "CT scan of the chest (no contrast)", "Chest CT", "CT", "Chest",
     "ct chest lung nodule cough", "A detailed scan of the lungs and chest, for example to follow a lung nodule.",
     "5–10 min"),
    ("71271", "ct-lung-screen", "Low-dose CT lung cancer screening", "Lung screening CT", "CT", "Chest",
     "lung cancer screening low dose ct smoker",
     "A yearly low-dose chest CT for people at high risk of lung cancer. Often covered at $0 as preventive care.",
     "5 min"),
    ("74176", "ct-abd-pel-noncon", "CT scan of the abdomen & pelvis (no contrast)", "Abdomen CT (no contrast)", "CT",
     "Abdomen", "ct abdomen pelvis kidney stone flank pain no contrast",
     "A CT of the belly and pelvis without dye, commonly used to look for kidney stones.", "5–10 min"),
    ("74177", "ct-abd-pel", "CT scan of the abdomen & pelvis (with contrast)", "Abdomen & pelvis CT", "CT", "Abdomen",
     "ct cat abdomen pelvis belly stomach appendicitis contrast",
     "A CT of the belly and pelvis with IV dye, for abdominal pain, infections or cancer staging.", "10–15 min"),
    ("72125", "ct-neck-spine", "CT scan of the neck spine (no contrast)", "Neck spine CT", "CT", "Spine",
     "ct cervical spine neck injury", "A CT of the bones of the neck, often after an accident.", "5–10 min"),
    ("70551", "mri-brain", "MRI of the brain (no contrast)", "Brain MRI (no contrast)", "MRI", "Head",
     "mri brain head neuro headache", "A magnetic scan of the brain without dye.", "30–45 min"),
    ("70553", "mri-brain-contrast", "MRI of the brain (without & with contrast)", "Brain MRI", "MRI", "Head",
     "mri brain head contrast neuro headache ms stroke seizure tumor",
     "A detailed magnetic scan of the brain, before and after an IV dye. Common for seizures, MS or tumors.",
     "45–60 min"),
    ("72141", "mri-neck-spine", "MRI of the neck spine (no contrast)", "Neck spine MRI", "MRI", "Spine",
     "mri cervical spine neck pain arm numbness", "A magnetic scan of the neck spine, discs and nerves.", "30–45 min"),
    ("72148", "mri-low-back", "MRI of the lower back (no contrast)", "Lower back MRI", "MRI", "Spine",
     "mri lumbar spine lower back sciatica disc herniation back pain",
     "A magnetic scan of the lower spine for back pain with leg symptoms (sciatica).", "30–45 min"),
    ("73721", "mri-knee", "MRI of the knee, ankle or hip joint (no contrast)", "Knee / leg joint MRI", "MRI", "Leg",
     "mri knee ankle hip joint leg acl meniscus sports injury",
     "A magnetic scan of one leg joint (most often the knee) for torn ligaments or cartilage.", "30–45 min"),
    ("73221", "mri-shoulder", "MRI of the shoulder, elbow or wrist joint (no contrast)", "Shoulder / arm joint MRI",
     "MRI", "Arm", "mri shoulder rotator cuff elbow wrist joint arm",
     "A magnetic scan of one arm joint, often the shoulder for rotator cuff injuries.", "30–45 min"),
    ("74183", "mri-abdomen", "MRI of the abdomen (without & with contrast)", "Abdomen MRI", "MRI", "Abdomen",
     "mri abdomen liver pancreas kidney", "A magnetic scan of the liver, pancreas and kidneys with IV dye.",
     "45–60 min"),
    ("76700", "us-abdomen", "Ultrasound of the abdomen (complete)", "Abdominal ultrasound", "Ultrasound", "Abdomen",
     "ultrasound sonogram abdomen liver gallbladder gallstones kidney",
     "A painless sound-wave scan of the liver, gallbladder, pancreas, spleen and kidneys. No radiation.",
     "20–30 min"),
    ("76705", "us-abdomen-limited", "Ultrasound of the abdomen (limited, e.g. gallbladder)", "Gallbladder ultrasound",
     "Ultrasound", "Abdomen", "ultrasound gallbladder right upper quadrant limited",
     "A focused ultrasound of one area, most often the gallbladder.", "15–20 min"),
    ("76856", "us-pelvis", "Pelvic ultrasound (through the belly, non-pregnancy)", "Pelvic ultrasound", "Ultrasound",
     "Pelvis", "ultrasound pelvis uterus ovaries bladder", "A sound-wave scan of the pelvis through the belly.",
     "20–30 min"),
    ("76830", "us-transvaginal", "Transvaginal ultrasound (non-pregnancy)", "Transvaginal ultrasound", "Ultrasound",
     "Pelvis", "ultrasound transvaginal pelvic uterus ovaries gynecology",
     "An internal ultrasound of the uterus and ovaries, often for pelvic pain or bleeding.", "15–30 min"),
    ("76805", "us-pregnancy", "Pregnancy ultrasound (after 14 weeks, one baby)", "Pregnancy ultrasound",
     "Ultrasound", "Pelvis", "ultrasound pregnancy ob obstetric anatomy scan baby prenatal sonogram",
     "A standard ultrasound in the 2nd or 3rd trimester to check the baby's growth and anatomy.", "30–45 min"),
    ("76536", "us-thyroid", "Ultrasound of the thyroid / neck", "Thyroid ultrasound", "Ultrasound", "Neck",
     "ultrasound thyroid neck nodule", "A sound-wave scan of the thyroid and neck.", "15–20 min"),
    ("76642", "us-breast", "Breast ultrasound (one breast, limited)", "Breast ultrasound", "Ultrasound", "Breast",
     "ultrasound breast lump", "A focused ultrasound of a breast lump or a spot seen on a mammogram.", "15–20 min"),
    ("93880", "us-carotid", "Ultrasound of the neck arteries (carotid)", "Carotid ultrasound", "Ultrasound", "Neck",
     "carotid ultrasound duplex stroke neck arteries", "Checks the neck arteries for narrowing.", "30 min"),
    ("77065", "mammo-diag-one", "Diagnostic mammogram (one breast)", "Diagnostic mammogram (one side)", "Mammogram",
     "Breast", "mammogram mammography breast diagnostic lump",
     "A detailed mammogram of one breast to follow up a lump, a symptom or an abnormal screening.", "20–30 min"),
    ("77066", "mammo-diag-both", "Diagnostic mammogram (both breasts)", "Diagnostic mammogram (both)", "Mammogram",
     "Breast", "mammogram mammography breast diagnostic both",
     "A detailed mammogram of both breasts after a symptom or an abnormal screening.", "20–30 min"),
    ("77067", "mammo-screen", "Screening mammogram (both breasts)", "Screening mammogram", "Mammogram", "Breast",
     "mammogram screening yearly breast cancer",
     "The routine yearly mammogram for people with no symptoms. Usually covered at $0 as preventive care.",
     "15–20 min"),
    ("77080", "dexa", "Bone density scan (DEXA)", "Bone density (DEXA)", "X-ray", "Hip/spine",
     "dexa bone density osteoporosis dxa", "A low-dose X-ray that measures bone strength.", "10–20 min"),
    ("71046", "xr-chest", "Chest X-ray (2 views)", "Chest X-ray", "X-ray", "Chest",
     "xray x-ray chest pneumonia cough lungs", "Two standard X-ray pictures of the chest.", "5–10 min"),
    ("72110", "xr-low-back", "X-ray of the lower back (4+ views)", "Lower back X-ray", "X-ray", "Spine",
     "xray x-ray lumbar spine lower back radiograph", "X-ray pictures of the lower spine from at least four angles.",
     "10–15 min"),
    ("73562", "xr-knee", "X-ray of the knee (3 views)", "Knee X-ray", "X-ray", "Leg",
     "xray x-ray knee injury arthritis", "Three X-ray pictures of the knee.", "5–10 min"),
    ("73030", "xr-shoulder", "X-ray of the shoulder (2+ views)", "Shoulder X-ray", "X-ray", "Arm",
     "xray x-ray shoulder injury", "X-ray pictures of the shoulder.", "5–10 min"),
    ("73610", "xr-ankle", "X-ray of the ankle (3+ views)", "Ankle X-ray", "X-ray", "Leg",
     "xray x-ray ankle sprain fracture", "X-ray pictures of the ankle, often after a twist or fall.", "5–10 min"),
    ("73130", "xr-hand", "X-ray of the hand (3+ views)", "Hand X-ray", "X-ray", "Arm",
     "xray x-ray hand finger fracture", "X-ray pictures of the hand.", "5–10 min"),
    ("78815", "pet-ct", "PET/CT scan (skull base to mid-thigh)", "PET/CT", "PET", "Body",
     "pet ct cancer staging scan", "A scan that shows how active tissues are, mostly for cancer staging.",
     "1.5–2 hours"),
]

# extra sites allowed per modality for the technical/global part, beyond radiology and imaging sites
MODALITY_SITES = {
    "X-ray": ["ortho", "primary", "urgent"],
    "Ultrasound": ["obgyn", "cardio", "primary"],
    "Mammogram": [],
    "DEXA": ["primary", "obgyn"],
    "CT": [],
    "MRI": ["ortho"],
    "PET": [],
}


def _imaging():
    out = []
    for code, pid, name, short, mod, body, kw, about, time in IMAGING:
        extra = MODALITY_SITES.get(mod, [])
        if pid == "dexa":
            extra = MODALITY_SITES["DEXA"]
        if pid == "us-pregnancy":
            extra = ["obgyn"]
        if pid == "us-carotid":
            extra = ["cardio"]
        out.append({
            "id": pid, "name": name, "short": short, "cat": "Imaging", "modality": mod, "body": body,
            "keywords": kw, "about": about, "time": time, "kind": "imaging", "codes": [code],
            "who": {"pro": ["radiology"] + (["cardio"] if pid == "us-carotid" else []) + (["obgyn"] if mod == "Ultrasound" and body == "Pelvis" else []),
                    "tc": ["imaging_site"] + extra, "global": ["radiology", "imaging_site"] + extra},
            "peds": mod in ("CT", "MRI", "X-ray", "Ultrasound") and body not in ("Breast",),
            "preventive": pid in ("mammo-screen", "ct-lung-screen"),
        })
    return out


OTHER = [
    {"id": "office-new", "name": "Office visit — new patient (moderate)", "short": "New-patient visit",
     "cat": "Visits", "keywords": "doctor visit new patient primary care checkup sick visit appointment",
     "about": "A first visit with a doctor or nurse practitioner for a new problem, at a typical (moderate) level.",
     "time": "30–45 min", "kind": "visit", "codes": ["99203"], "alt": ["99204"], "who": {"any": ["primary"]}},
    {"id": "office-return", "name": "Office visit — returning patient (moderate)", "short": "Returning-patient visit",
     "cat": "Visits", "keywords": "doctor visit follow up established primary care sick visit appointment",
     "about": "A visit with your own doctor or nurse practitioner for a problem, at the most common level.",
     "time": "15–30 min", "kind": "visit", "codes": ["99213"], "alt": ["99214"], "who": {"any": ["primary"]}},
    {"id": "urgent-care", "name": "Urgent care visit", "short": "Urgent care visit", "cat": "Visits",
     "keywords": "urgent care walk in clinic sick visit flu strep cold",
     "about": "A walk-in visit at an urgent care clinic. Some insurers pay these clinics one flat amount per visit; "
              "others pay a visit code plus an urgent-care fee.",
     "time": "30–60 min", "kind": "visit", "codes": ["99213", "99203"], "addon": ["S9083", "S9088"],
     "who": {"any": ["urgent"]}, "place_kind": "urgent"},
    {"id": "physical-adult", "name": "Yearly physical (adult, 40–64)", "short": "Adult physical", "cat": "Visits",
     "keywords": "annual physical wellness preventive checkup",
     "about": "A yearly preventive checkup. Usually covered at $0 in-network under ACA preventive-care rules.",
     "time": "30–45 min", "kind": "visit", "codes": ["99396"], "alt": ["99386"], "who": {"any": ["primary"]},
     "preventive": True},
    {"id": "psych-eval", "name": "Psychiatric evaluation (first visit)", "short": "Psychiatry first visit",
     "cat": "Mental health", "keywords": "psychiatrist evaluation mental health depression anxiety adhd medication",
     "about": "A first visit with a psychiatrist or psychiatric nurse practitioner, including a medical evaluation.",
     "time": "60–90 min", "kind": "visit", "codes": ["90792"], "who": {"any": ["psych_md"]}},
    {"id": "psych-followup", "name": "Psychiatry follow-up (medication management)", "short": "Psychiatry follow-up",
     "cat": "Mental health", "keywords": "psychiatrist follow up medication management mental health",
     "about": "A returning visit with a psychiatrist or psychiatric NP to review medications, at the most common level.",
     "time": "20–30 min", "kind": "visit", "codes": ["99214"], "who": {"any": ["psych_md"]}},
    {"id": "therapy-60", "name": "Talk therapy session (53+ minutes)", "short": "Therapy (60 min)",
     "cat": "Mental health", "keywords": "therapy counseling psychotherapy therapist counselor mental health",
     "about": "One individual psychotherapy session of about an hour with a therapist, counselor or psychologist.",
     "time": "53–60 min", "kind": "service", "codes": ["90837"], "who": {"any": ["therapist"]}},
    {"id": "therapy-45", "name": "Talk therapy session (38–52 minutes)", "short": "Therapy (45 min)",
     "cat": "Mental health", "keywords": "therapy counseling psychotherapy therapist counselor mental health",
     "about": "One individual psychotherapy session of about 45 minutes.", "time": "45 min", "kind": "service",
     "codes": ["90834"], "who": {"any": ["therapist"]}},
    {"id": "therapy-intake", "name": "Therapy intake evaluation", "short": "Therapy intake", "cat": "Mental health",
     "keywords": "therapy intake first session psychological evaluation counselor",
     "about": "The first session with a therapist, counselor or psychologist to understand what you need.",
     "time": "60 min", "kind": "service", "codes": ["90791"], "who": {"any": ["therapist"]}},
    {"id": "tms", "name": "TMS therapy for depression (per treatment session)", "short": "TMS session",
     "cat": "Mental health", "keywords": "tms transcranial magnetic stimulation depression neuromodulation",
     "about": "Transcranial magnetic stimulation: a non-drug depression treatment given in daily sessions over "
              "several weeks. The first session (with motor-threshold mapping) is billed differently.",
     "time": "20–40 min", "kind": "service", "codes": ["90868", "90867"], "who": {"any": ["psych_md"]},
     "strict": True},
    {"id": "lab-cmp", "name": "Comprehensive metabolic panel (blood test)", "short": "CMP blood test", "cat": "Lab",
     "keywords": "blood test cmp metabolic panel kidney liver electrolytes lab",
     "about": "A common blood test for kidney and liver function, blood sugar and electrolytes.", "time": "5 min",
     "kind": "service", "codes": ["80053"], "who": {"any": ["lab"]}},
    {"id": "lab-lipid", "name": "Cholesterol panel (blood test)", "short": "Cholesterol test", "cat": "Lab",
     "keywords": "cholesterol lipid panel blood test lab", "about": "Measures cholesterol and triglycerides.",
     "time": "5 min", "kind": "service", "codes": ["80061"], "who": {"any": ["lab"]}},
    {"id": "lab-cbc", "name": "Complete blood count (blood test)", "short": "CBC blood test", "cat": "Lab",
     "keywords": "cbc complete blood count anemia blood test lab",
     "about": "Counts red cells, white cells and platelets.", "time": "5 min", "kind": "service", "codes": ["85025"],
     "who": {"any": ["lab"]}},
    {"id": "lab-a1c", "name": "Hemoglobin A1c (diabetes blood test)", "short": "A1c test", "cat": "Lab",
     "keywords": "a1c hemoglobin diabetes sugar blood test lab",
     "about": "Shows average blood sugar over about three months.", "time": "5 min", "kind": "service",
     "codes": ["83036"], "who": {"any": ["lab"]}},
    {"id": "lab-tsh", "name": "Thyroid test (TSH)", "short": "TSH thyroid test", "cat": "Lab",
     "keywords": "thyroid tsh blood test lab", "about": "Checks how well the thyroid is working.", "time": "5 min",
     "kind": "service", "codes": ["84443"], "who": {"any": ["lab"]}},
    {"id": "pt-eval", "name": "Physical therapy evaluation", "short": "PT evaluation", "cat": "Therapy",
     "keywords": "physical therapy pt evaluation rehab back knee shoulder",
     "about": "The first physical therapy visit, where the therapist assesses you and plans treatment.",
     "time": "45–60 min", "kind": "service", "codes": ["97162", "97161"], "who": {"any": ["pt"]}},
    {"id": "pt-exercise", "name": "Physical therapy exercise (per 15 minutes)", "short": "PT exercise (15 min)",
     "cat": "Therapy", "keywords": "physical therapy pt exercise rehab",
     "about": "Therapeutic exercise with a physical therapist, billed per 15 minutes. A visit is usually 2–4 units.",
     "time": "15 min unit", "kind": "service", "codes": ["97110"], "who": {"any": ["pt"]}},
    {"id": "ecg", "name": "Electrocardiogram (ECG/EKG)", "short": "ECG", "cat": "Heart",
     "keywords": "ecg ekg heart rhythm electrocardiogram", "about": "A quick recording of the heart's rhythm.",
     "time": "10 min", "kind": "service", "codes": ["93000"], "who": {"any": ["primary", "cardio"]}},
    {"id": "echo", "name": "Heart ultrasound (echocardiogram)", "short": "Echocardiogram", "cat": "Heart",
     "keywords": "echo echocardiogram heart ultrasound murmur heart failure",
     "about": "An ultrasound of the heart's chambers and valves.", "time": "45–60 min", "kind": "imaging",
     "codes": ["93306"], "who": {"pro": ["cardio"], "tc": ["cardio", "imaging_site"], "global": ["cardio", "imaging_site"]}},
    {"id": "stress-test", "name": "Treadmill stress test", "short": "Stress test", "cat": "Heart",
     "keywords": "stress test treadmill exercise heart chest pain",
     "about": "An ECG recorded while you walk on a treadmill.", "time": "45–60 min", "kind": "service",
     "codes": ["93015"], "who": {"any": ["cardio"]}},
    {"id": "sleep-study", "name": "Sleep study in a sleep lab", "short": "Sleep study", "cat": "Other",
     "keywords": "sleep study apnea polysomnography snoring",
     "about": "An overnight study in a sleep lab to diagnose sleep apnea.", "time": "Overnight", "kind": "imaging",
     "codes": ["95810"], "who": {"pro": ["sleep"], "tc": ["sleep", "hospital"], "global": ["sleep", "hospital"]}},
    {"id": "colonoscopy-screen", "name": "Screening colonoscopy (doctor's fee)", "short": "Screening colonoscopy",
     "cat": "Procedures", "keywords": "colonoscopy screening colon cancer gi",
     "about": "The gastroenterologist's fee for a screening colonoscopy. Usually $0 as preventive care; the facility "
              "and anesthesia bill separately.", "time": "30–60 min", "kind": "service", "codes": ["G0121", "45378"],
     "who": {"any": ["gi"]}, "preventive": True},
    {"id": "joint-injection", "name": "Joint injection (large joint, e.g. knee or shoulder)", "short": "Joint injection",
     "cat": "Procedures", "keywords": "joint injection cortisone steroid knee shoulder",
     "about": "A steroid or other injection into a large joint, without imaging guidance.", "time": "15 min",
     "kind": "service", "codes": ["20610"], "who": {"any": ["ortho", "primary"]}},
]


def catalog() -> list[dict]:
    return _imaging() + OTHER


def all_codes() -> list[str]:
    out = []
    for p in catalog():
        out += p["codes"] + p.get("alt", []) + p.get("addon", [])
    return sorted(set(out))
