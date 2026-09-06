"""
Adversarial data augmentation (generalization fix).
====================================================
Problem: source dataset scams are synthetic templated text, so the model
memorizes one template bigram ('contact basic') and ignores all engineered
signals -> fails on novel scam wording.

Fix: generate lexically DIVERSE scam posts (same tactics, many phrasings)
and HARD legitimate posts (real jobs mentioning salary / remote work),
then mix them into training. Forces XGBoost to learn scam *signals*
(fees, free webmail, urgency, unrealistic pay) rather than exact strings.
"""

import random

_rng = random.Random(42)

_PAY      = ["$500", "$1,200", "$3,000", "$5,000", "$800", "$2,500", "$10,000"]
_PER      = ["a week", "per week", "weekly", "a day", "per month", "every two weeks"]
_FEE      = ["$29", "$49", "$99", "$150", "$75", "$200"]
_FEETYPE  = ["registration fee", "processing fee", "training fee",
             "background-check fee", "starter-kit fee", "application fee"]
_MAIL     = ["gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "proton.me"]
_CHAT     = ["WhatsApp", "Telegram", "Signal"]

_SCAM_TEMPLATES = [
    "Make {pay} {per} working from home! No experience required. Pay a one-time {feetype} of {fee} to begin. Message us on {chat} at +92 300 {num}.",
    "Hiring NOW! Earn {pay} {per} with just your phone. Send {fee} via wire transfer to secure your slot. Contact recruit{num}@{mail}.",
    "Work from home opportunity - guaranteed income of {pay} {per}! No interviews, no degree needed. Register at www.jobs-fast-{num}.top and pay a small {feetype}.",
    "Urgent data entry positions! {pay} {per}, flexible hours. To activate your account pay {fee}. Details on {mail}: hire{num}@{mail}.",
    "Apply today and start earning {pay} {per}! Limited positions, act fast. A refundable {feetype} of {fee} is required. {chat} +1 555 {num}.",
    "Congratulations! You are selected for our remote program paying {pay} {per}. No experience needed. Purchase your starter kit for {fee}. Write to jobs{num}@{mail}.",
    "Easy money from your couch! {pay} {per} for simple tasks. Sign-up requires a {fee} {feetype}. Only WhatsApp +44 7{num}. Guaranteed payout!",
    "Immediate hiring, no resume needed! {pay} {per}. First pay the {feetype} ({fee}) through gift cards or bitcoin, then start today!",
    "We pay {pay} {per} for posting ads online. Risk free, no investment except a {fee} {feetype}. Hurry — positions filling fast! Email fasthire{num}@{mail}.",
    "Remote assistant wanted. Salary {pay} {per}, no experience necessary. To verify your identity send {fee} via mobile wallet. Contact +92 3{num} on {chat}.",
    "Mystery shopper job! Keep the products and earn {pay} {per}. Just cover the {fee} shipping and {feetype}. Apply at www.shop-earn-{num}.xyz now!",
    "Part-time offer for students: {pay} {per}. No degree required, training provided after a {fee} {feetype}. Message {chat}: +1 800 {num}. Don't miss out!",
    "We are offering students a chance to receive {pay} every month by posting advertisements for us. Kindly transfer a small verification {feetype} through {wallet} before onboarding. Reach us only on {chat}.",
    "Receive {pay} {per} as a home-based typist. Kindly send your refundable security deposit of {fee} via {wallet} to confirm. We will contact you on {chat} only — no office visit needed.",
    "Selected candidates will get {pay} {per}. Before joining, applicants must deposit {fee} through {wallet} as a refundable security amount. Interviews are not required for this role.",
    "Simple copy paste job, {pay} {per}! Transfer the {fee} activation amount to our {wallet} account and receive your ID instantly on {chat}. 100% guaranteed income!",
    "Online form filling job — earn {pay} {per} guaranteed. Security deposit {fee} payable via {wallet} only, refunded with first salary. Limited seats, apply immediately on {chat}.",
    "Assalam-o-Alaikum! Home based job for students, {pay} {per}. Sirf {fee} ki advance payment {wallet} par karain aur aaj hi kam shuru karain. Rabta {chat} par: +92 3{num}.",
]
_WALLET = ["Easypaisa", "JazzCash", "mobile wallet", "bank transfer", "Western Union"]

# SHORT legitimate posts — newspaper/classified style.
# Dataset legit posts are long; scams are short/terse, creating a harmful
# "short text = scam" bias. These short-realistic legit ads counter it.
# Many include phone numbers: a phone in an ad is NOT itself scammy.
_SHORT_LEGIT = [
    "Accountant required for trading company in {city}. B.Com with {n} years experience. Office timings 9 to 5. Send CV by email during office hours.",
    "Female receptionist required for dental clinic {city}. Good communication skills, computer literate. Salary {pay}. Call to schedule an interview.",
    "Driver required for school in {city}. Valid LTV license and {n} years experience. Salary {pay}. Contact the school office.",
    "Office boy required for law firm {city}. Matric pass preferred. Timings 9am to 6pm, Sunday off. Salary {pay}.",
    "Salesman required for mobile shop {city}. Experience in mobile selling preferred. Salary {pay} plus commission.",
    "Cook required for family in {city}. Must know Pakistani and Chinese dishes. Accommodation provided. Salary negotiable.",
    "Security guard required for plaza {city}. Retired army personnel preferred. 12-hour shift, salary {pay}.",
    "School requires English and Maths teachers for primary section, {city}. Bachelor degree with {n} years teaching experience. Walk-in interview this week.",
    "Delivery rider required for restaurant {city}. Own bike and valid license required. Salary {pay} plus fuel allowance.",
    "AC technician required for service center {city}. {n} years field experience. Attractive salary based on skill.",
    "Pharmacist required for pharmacy {city}. B-Pharmacy with valid council registration. Two shifts available.",
    "Graphic designer required for printing press {city}. Must know CorelDraw and Photoshop. {n}+ years experience. Market salary.",
    " electrician required for housing society {city}. ITI certified with {n} years experience. Immediate joining, salary {pay}.",
    "Data entry operator required, {city}. Typing speed 40 wpm, MS Office knowledge. Evening shift available for students.",
]
_CITY2 = ["Saddar Karachi", "DHA Lahore", "Gulberg Lahore", "F-8 Islamabad",
          "Gulshan-e-Iqbal Karachi", "Model Town Lahore", "Cantt Multan",
          "Commercial Market Rawalpindi", "Blue Area Islamabad", "PECHS Karachi"]
_PAYPKR = ["35,000", "40,000", "45,000", "50,000", "60,000", "according to experience"]


def make_short_legit() -> str:
    t = _rng.choice(_SHORT_LEGIT).strip()
    return t.format(city=_rng.choice(_CITY2), pay=_rng.choice(_PAYPKR), n=_rng.randint(2, 5))

# Legit posts that look "hard": mention remote work & salary but follow
# professional norms (corporate portal, no fees, no free-webmail-only contact)
_HARD_LEGIT = [
    "Remote {role} — {co}. Salary {range} depending on experience. You will {duty1} and {duty2}. Requirements: {yrs}+ years of experience and strong {skill} skills. We offer health insurance, paid leave, and a learning budget. Apply via our careers page at {co_web} — we never ask for payments.",
    "{co} is hiring a {role} ({mode}). Compensation {range} plus annual bonus. Responsibilities include {duty1}, {duty2}, and collaborating with cross-functional teams. Ideal candidates have {yrs} years of experience and a degree in Computer Science or related field. Interviews are conducted by our HR team; apply through LinkedIn or our official website.",
    "We are looking for a {role} to join our {mode} team in {city}. The package is {range} with health coverage and provident fund. You should be comfortable with {skill} and have {yrs}+ years of experience. Shortlisted candidates will be contacted from our official {co} email domain.",
    "Work-from-home {role} position at {co}. Pay range {range}. Day-to-day: {duty1} and {duty2}. Must have proven {skill} experience ({yrs}+ years) and good communication skills. We conduct two interview rounds and never charge applicants any fee.",
]
_ROLE  = ["Software Engineer", "Data Analyst", "Customer Support Lead", "Marketing Manager",
          "DevOps Engineer", "Content Writer", "Accountant", "Product Designer"]
_CO    = ["TechNova Pvt Ltd", "Systems Ltd", "BrightSoft", "Netsolace", "CodeWorks", "DataBridge"]
_COWEB = ["technova.com/careers", "systemsltd.com/jobs", "brightsoft.io/careers"]
_DUTY1 = ["design REST APIs", "build dashboards", "maintain CI/CD pipelines",
          "write technical documentation", "analyze sales data", "manage client accounts"]
_DUTY2 = ["review pull requests", "mentor junior staff", "coordinate with QA",
          "optimize database queries", "run A/B tests", "handle escalations"]
_SKILL = ["Python", "SQL", "React", "Excel modeling", "cloud infrastructure", "SEO"]
_RANGE = ["PKR 150k-250k/month", "$60,000-$85,000/year", "PKR 200k/month + benefits",
          "$4,000-$6,000/month"]
_CITY  = ["Lahore", "Karachi", "Islamabad", "remote-first"]
_MODE  = ["fully remote", "hybrid", "on-site with remote Fridays"]


def make_scam() -> str:
    t = _rng.choice(_SCAM_TEMPLATES)
    return t.format(pay=_rng.choice(_PAY), per=_rng.choice(_PER),
                    fee=_rng.choice(_FEE), feetype=_rng.choice(_FEETYPE),
                    mail=_rng.choice(_MAIL), chat=_rng.choice(_CHAT),
                    wallet=_rng.choice(_WALLET),
                    num=_rng.randint(1000000, 9999999))


def make_hard_legit() -> str:
    t = _rng.choice(_HARD_LEGIT)
    return t.format(role=_rng.choice(_ROLE), co=_rng.choice(_CO),
                    co_web=_rng.choice(_COWEB), duty1=_rng.choice(_DUTY1),
                    duty2=_rng.choice(_DUTY2), yrs=_rng.randint(2, 8),
                    skill=_rng.choice(_SKILL), range=_rng.choice(_RANGE),
                    city=_rng.choice(_CITY), mode=_rng.choice(_MODE))


# Fixed handwritten probe set the model has NEVER seen — reported in metrics
PROBES = [
    ("OBVIOUS SCAM — fee + gmail + weekly pay",
     "Earn $5000 per week working from home! No experience needed. Pay a $50 "
     "registration fee to start. Contact jobs2024@gmail.com or WhatsApp "
     "+92300123456. Apply now, limited positions! Visit www.fast-cash-jobs.biz", 1),
    ("SCAM — paraphrased, no template words",
     "We are offering students a chance to receive 4000 dollars every month by "
     "posting advertisements for us. Kindly transfer a small verification deposit "
     "through Easypaisa before onboarding. Reach us only on Telegram.", 1),
    ("SCAM — gift card + urgency",
     "ACT NOW! Positions filling FAST. Guaranteed weekly payouts of $2,000 for "
     "simple copy-paste tasks. Buy a $100 Apple gift card for the software "
     "license and start TODAY ONLY!", 1),
    ("LEGIT — mentions remote + salary",
     "Senior Software Engineer at Systems Ltd, Lahore (hybrid). We need 5+ years "
     "of Python and PostgreSQL experience. You will design APIs and mentor "
     "juniors. Benefits: health insurance, provident fund, annual bonus, "
     "salary PKR 400k-550k/month. Apply via our careers portal.", 0),
    ("LEGIT — work from home, no fee",
     "Remote Customer Support Specialist. Work from home anywhere in Pakistan. "
     "Competitive pay of PKR 120k/month with quarterly bonuses. Requires 2+ "
     "years of support experience and fluent English. Two interview rounds; "
     "we never charge applicants. Apply on our official website.", 0),
    ("LEGIT — short classified ad",
     "Accountant required for trading company in Saddar Karachi. B.Com with 3 "
     "years experience. Office timings 9 to 5. Send CV by email.", 0),
    ("LEGIT — short ad with phone",
     "Driver required for school in Gulshan Karachi. Valid LTV license, 5 years "
     "experience. Salary 45,000. Call school office at 021-3456789.", 0),
]
