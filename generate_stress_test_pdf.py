"""
Generates a realistic 100+ page Australian Family Trust Deed compliance bundle.
Simulates the messy reality of what AML analysts actually receive:
  - Original trust deed with dense legal boilerplate
  - Multiple variation deeds over years (adding/removing beneficiaries)
  - Change of trustee documentation
  - ASIC company extracts
  - Solicitor correspondence
  - Trustee meeting minutes
  - Certified ID copy placeholders
  - Stamp duty assessments
  - Power of Attorney documentation
  - Foreign entity documentation
  - Handwritten margin annotations and amendments
  - Scan artifacts and certification stamps

Ground truth is printed at the end for pipeline validation.
"""

from fpdf import FPDF
import os
import random

random.seed(42)  # Reproducible "randomness"


class TrustBundlePDF(FPDF):
    """Custom PDF class for trust deed compliance bundles."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._current_doc_title = ""
        self._show_header = True

    def set_doc_title(self, title: str):
        self._current_doc_title = title

    def header(self):
        if not self._show_header:
            return
        self.set_font("Helvetica", "I", 7)
        self.cell(0, 5, self._current_doc_title, align="L")
        self.cell(0, 5, f"Page {self.page_no()}", align="R", new_x="LMARGIN", new_y="NEXT")
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(3)

    def section_heading(self, number, title):
        self.set_font("Helvetica", "B", 13)
        self.ln(4)
        self.cell(0, 8, f"{number}. {title}", new_x="LMARGIN", new_y="NEXT")
        self.ln(2)

    def sub_heading(self, number, title):
        self.set_font("Helvetica", "B", 11)
        self.ln(2)
        self.cell(0, 7, f"    {number}  {title}", new_x="LMARGIN", new_y="NEXT")
        self.ln(1)

    def body(self, text):
        self.set_font("Helvetica", "", 10)
        self.multi_cell(0, 5.5, text)
        self.ln(1.5)

    def clause(self, number, text):
        self.set_font("Helvetica", "", 10)
        self.multi_cell(0, 5.5, f"({number})  {text}")
        self.ln(1)

    def handwritten_note(self, text):
        """Simulates a handwritten margin note / amendment."""
        self.set_font("Courier", "I", 9)
        self.set_text_color(0, 0, 180)
        self.multi_cell(0, 5, f"[HANDWRITTEN NOTE]: {text}")
        self.set_text_color(0, 0, 0)
        self.set_font("Helvetica", "", 10)
        self.ln(2)

    def stamp(self, text):
        """Simulates a certification stamp."""
        self.set_font("Helvetica", "B", 11)
        self.set_text_color(180, 0, 0)
        y = self.get_y()
        self.rect(12, y, 186, 20)
        self.ln(3)
        self.cell(0, 7, text, align="C", new_x="LMARGIN", new_y="NEXT")
        self.set_font("Helvetica", "", 9)
        self.cell(0, 7, "Authorised Representative", align="C", new_x="LMARGIN", new_y="NEXT")
        self.set_text_color(0, 0, 0)
        self.ln(8)

    def scan_artifact(self):
        """Simulates scan noise / artifacts at bottom of page."""
        artifacts = [
            "[Scan quality: Fair -- some text may be illegible]",
            "[Document scanned from microfiche -- original held in archive]",
            "[Page partially obscured -- see physical file for full text]",
            "[OCR confidence: 87% -- manual verification recommended]",
            "[Scanned at 300 DPI -- Date of scan: 14/02/2024]",
            "[Original document shows signs of water damage in lower margin]",
        ]
        self.set_font("Courier", "I", 7)
        self.set_text_color(120, 120, 120)
        self.cell(0, 4, random.choice(artifacts), align="C", new_x="LMARGIN", new_y="NEXT")
        self.set_text_color(0, 0, 0)

    def separator_page(self, title, subtitle=""):
        """Creates a document separator page (like a tab divider in a physical file)."""
        self.add_page()
        self.ln(60)
        self.set_font("Helvetica", "B", 20)
        self.cell(0, 12, title, align="C", new_x="LMARGIN", new_y="NEXT")
        if subtitle:
            self.ln(5)
            self.set_font("Helvetica", "", 14)
            self.cell(0, 10, subtitle, align="C", new_x="LMARGIN", new_y="NEXT")
        self.ln(20)
        self.set_font("Helvetica", "I", 10)
        self.cell(0, 8, "--- DOCUMENT SEPARATOR ---", align="C", new_x="LMARGIN", new_y="NEXT")


def add_original_deed(pdf: TrustBundlePDF):
    """Generates the original trust deed (~25 pages of dense legal text)."""
    pdf.set_doc_title("THE PEMBERTON FAMILY TRUST -- Original Deed dated 8 November 2017")

    # ---- Title Page ----
    pdf.add_page()
    pdf._show_header = False
    pdf.ln(25)
    pdf.set_font("Helvetica", "B", 24)
    pdf.cell(0, 15, "DEED OF TRUST", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(8)
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 12, "THE PEMBERTON FAMILY TRUST", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(10)
    pdf.set_font("Helvetica", "", 12)
    pdf.cell(0, 8, "ABN: 53 714 289 301", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 8, "Date of Settlement: 8 November 2017", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(15)
    pdf.cell(0, 8, "Prepared by:", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Henderson Chambers & Partners", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 8, "Barristers, Solicitors & Notaries Public", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 8, "Level 18, 101 Collins Street, Melbourne VIC 3000", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 8, "DX 128 Melbourne", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(20)
    pdf.set_font("Helvetica", "I", 9)
    pdf.cell(0, 6, "This document contains 42 pages including this cover page.", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, "All enquiries: Partner Reference HCP/MXP/2017/4481", align="C", new_x="LMARGIN", new_y="NEXT")

    pdf._show_header = True
    pdf.stamp("CERTIFIED TRUE COPY -- Henderson Chambers & Partners")

    # ---- Table of Contents ----
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, "TABLE OF CONTENTS", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(8)

    toc_entries = [
        ("1", "Parties", "3"), ("2", "Recitals", "4"), ("3", "Definitions and Interpretation", "5"),
        ("4", "Declaration of Trust", "9"), ("5", "Trust Fund", "10"), ("6", "Powers of the Trustee", "11"),
        ("7", "Investment Powers", "14"), ("8", "Power to Borrow", "15"),
        ("9", "Power to Carry on Business", "16"), ("10", "Distribution of Income", "17"),
        ("11", "Distribution of Capital", "18"), ("12", "Accumulation of Income", "19"),
        ("13", "Addition and Removal of Beneficiaries", "20"),
        ("14", "Appointment and Removal of Trustee", "21"),
        ("15", "Powers of the Appointor", "22"), ("16", "Guardian", "23"),
        ("17", "Trustee Remuneration and Indemnity", "24"),
        ("18", "Accounts and Records", "25"), ("19", "Trustee Liability", "26"),
        ("20", "Amendment of Deed", "27"), ("21", "Resettlement", "28"),
        ("22", "Vesting", "29"), ("23", "Governing Law", "30"),
        ("24", "Severability", "30"), ("25", "Notices", "31"),
        ("Schedule 1", "Beneficiaries", "32"), ("Schedule 2", "Initial Trust Property", "34"),
        ("Schedule 3", "Excluded Persons", "35"),
        ("", "Execution", "36"),
    ]

    pdf.set_font("Helvetica", "", 10)
    for num, title, page in toc_entries:
        label = f"  {num}    {title}" if num else f"         {title}"
        dots = "." * (60 - len(label) - len(page))
        pdf.cell(0, 6, f"{label} {dots} {page}", new_x="LMARGIN", new_y="NEXT")

    # ---- Parties ----
    pdf.add_page()
    pdf.section_heading("1", "PARTIES")
    pdf.body(
        "This Deed of Trust is made on the 8th day of November 2017 between "
        "the following parties:"
    )

    pdf.sub_heading("1.1", "THE SETTLOR")
    pdf.body(
        "Geoffrey Alan Henderson of Level 18, 101 Collins Street, Melbourne VIC 3000, "
        "Solicitor (hereinafter referred to as 'the Settlor'), who has settled the "
        "initial trust property of Ten Dollars ($10.00) upon the terms and conditions "
        "set out in this Deed. The Settlor shall have no further role in the "
        "administration of the Trust and shall not be a Beneficiary of the Trust."
    )

    pdf.sub_heading("1.2", "THE TRUSTEE")
    pdf.body(
        "Pemberton Holdings Pty Ltd (ACN 618 492 713), a company duly incorporated "
        "under the Corporations Act 2001 (Cth) in the State of Victoria and having "
        "its registered office at Unit 7, 34 Chapel Street, South Yarra VIC 3141 "
        "(hereinafter referred to as 'the Trustee'). The sole director and company "
        "secretary of the Trustee as at the date of this Deed is Marcus Edward "
        "Pemberton."
    )

    pdf.sub_heading("1.3", "THE APPOINTOR")
    pdf.body(
        "Marcus Edward Pemberton of 12 Lansdowne Crescent, Toorak VIC 3142, "
        "Company Director, born 22 June 1975 (hereinafter referred to as 'the "
        "Appointor'). The Appointor shall have the power to appoint and remove "
        "the Trustee in accordance with Clause 14 of this Deed."
    )

    pdf.sub_heading("1.4", "THE GUARDIAN")
    pdf.body(
        "Sarah Louise Pemberton of 12 Lansdowne Crescent, Toorak VIC 3142, "
        "Medical Practitioner, born 15 January 1978, being the spouse of the "
        "Appointor (hereinafter referred to as 'the Guardian'). The Guardian "
        "shall exercise oversight powers as specified in Clause 16."
    )

    pdf.handwritten_note(
        "Note: Sarah Pemberton nee Richardson. Marriage cert sighted 4/3/2018. "
        "-- G. Henderson"
    )

    # ---- Recitals ----
    pdf.section_heading("2", "RECITALS")
    for letter, text in [
        ("A", "The Settlor is desirous of creating a discretionary trust for the "
             "benefit of the Beneficiaries described in Schedule 1 of this Deed, to "
             "be known as 'The Pemberton Family Trust'."),
        ("B", "The Trustee has agreed to act as trustee of the Trust upon the terms "
             "and conditions set out herein and has acknowledged receipt of the "
             "initial settlement sum."),
        ("C", "The Settlor has paid to the Trustee the sum of Ten Dollars ($10.00) "
             "as the initial settlement sum, the receipt of which the Trustee hereby "
             "acknowledges."),
        ("D", "It is intended that the Trust shall be governed by the laws of the "
             "State of Victoria, Commonwealth of Australia, and that the Trust shall "
             "be irrevocable upon execution of this Deed."),
        ("E", "The parties acknowledge that the Trust is established as a "
             "discretionary trust for the purposes of Division 6 of Part III of the "
             "Income Tax Assessment Act 1936 (Cth) and that the Trustee shall have "
             "absolute discretion in the distribution of income and capital."),
    ]:
        pdf.clause(letter, text)

    # ---- Definitions (dense, multi-page) ----
    pdf.add_page()
    pdf.section_heading("3", "DEFINITIONS AND INTERPRETATION")
    pdf.body(
        "In this Deed, unless the context otherwise requires or a contrary intention "
        "appears, the following expressions shall have the meanings respectively "
        "ascribed to them:"
    )

    definitions = [
        ('"ABN"', 'means Australian Business Number as defined in the A New Tax System '
         '(Australian Business Number) Act 1999 (Cth).'),
        ('"Accountant"', 'means a person who is a member of the Institute of Chartered '
         'Accountants in Australia, CPA Australia, or the Institute of Public Accountants, '
         'or any successor body, and who holds a current practising certificate.'),
        ('"Appointor"', 'means the person named as Appointor in Clause 1.3 of this Deed '
         'or any person who subsequently becomes the Appointor pursuant to Clause 15.'),
        ('"Beneficiary"', 'means any person or entity listed in Schedule 1 of this Deed, '
         'together with any person or entity added as a Beneficiary by the Trustee in '
         'accordance with Clause 13, but excluding any person listed in Schedule 3 '
         '(Excluded Persons) or subsequently excluded in accordance with this Deed.'),
        ('"Business Day"', 'means a day other than a Saturday, Sunday, or public holiday '
         'in the State of Victoria.'),
        ('"CGT"', 'means Capital Gains Tax as imposed under Part IIIA of the Income Tax '
         'Assessment Act 1936 (Cth) or Part 3-1 of the Income Tax Assessment Act 1997 (Cth).'),
        ('"Child"', 'includes a natural child, an adopted child, a stepchild, an ex-nuptial '
         'child, and a child of a de facto relationship, and includes any child born after '
         'the date of this Deed.'),
        ('"Commissioner"', 'means the Commissioner of Taxation appointed under the Taxation '
         'Administration Act 1953 (Cth).'),
        ('"Corporations Act"', 'means the Corporations Act 2001 (Cth) as amended from time '
         'to time.'),
        ('"Distribution Date"', 'means the 30th day of June in each financial year, or such '
         'other date as the Trustee may determine by resolution prior to that date.'),
        ('"Eligible Person"', 'means any person who is: (a) a natural person who is a '
         'relative of the Primary Beneficiary within the meaning of section 13 of the '
         'Income Tax Assessment Act 1936 (Cth); (b) any company of which the Primary '
         'Beneficiary or any Beneficiary holds not less than 50% of the issued share '
         'capital; (c) the trustee of any other trust of which the Primary Beneficiary '
         'or any Beneficiary is a beneficiary; or (d) any charity or charitable institution '
         'approved under Division 30 of the Income Tax Assessment Act 1997 (Cth).'),
        ('"Financial Year"', 'means the year ending on 30 June or such other date as may '
         'be applicable for taxation purposes under applicable Commonwealth legislation.'),
        ('"GST"', 'means Goods and Services Tax as imposed under A New Tax System (Goods '
         'and Services Tax) Act 1999 (Cth).'),
        ('"Guardian"', 'means the person named as Guardian in Clause 1.4 of this Deed or '
         'any person who subsequently becomes the Guardian.'),
        ('"Income"', 'means the income of the Trust Fund for any Financial Year as '
         'determined by the Trustee in accordance with applicable accounting standards '
         'and the provisions of this Deed, and includes both ordinary income and statutory '
         'income for the purposes of the Income Tax Assessment Act 1997 (Cth).'),
        ('"Net Income"', 'has the meaning given to that expression in section 95 of the '
         'Income Tax Assessment Act 1936 (Cth).'),
        ('"Primary Beneficiary"', 'means Marcus Edward Pemberton, born 22 June 1975, '
         'as identified in Schedule 1 of this Deed.'),
        ('"Specified Beneficiary"', 'means any Beneficiary who is, at the relevant time, '
         'under a legal disability, including a minor or a person who lacks legal capacity.'),
        ('"Trust"', 'means the trust created by this Deed, known as The Pemberton Family Trust.'),
        ('"Trust Fund"', 'means: (a) the initial settlement sum; (b) all property from time '
         'to time held by the Trustee upon the trusts of this Deed; (c) all income derived '
         'from the Trust Fund; (d) all accretions to the Trust Fund; and (e) the proceeds '
         'of sale, conversion, or dealing with any property forming part of the Trust Fund.'),
        ('"Trust Period"', 'means the period commencing on the date of this Deed and ending '
         'on the Vesting Date.'),
        ('"Vesting Date"', 'means the earlier of: (a) the date which is eighty (80) years '
         'from the date of this Deed (being 8 November 2097); or (b) such earlier date as '
         'the Trustee may specify by written notice to the Appointor.'),
    ]

    for term, defn in definitions:
        pdf.set_font("Helvetica", "B", 10)
        w = pdf.get_string_width(term) + 4
        pdf.cell(w, 5.5, term)
        pdf.set_font("Helvetica", "", 10)
        pdf.multi_cell(0, 5.5, f"  {defn}")
        pdf.ln(2)

    pdf.body(
        "3.2  In this Deed, unless the context otherwise requires: "
        "(a) the singular includes the plural and vice versa; "
        "(b) a reference to a gender includes all genders; "
        "(c) headings are for convenience only and do not affect interpretation; "
        "(d) a reference to a statute includes all amendments, re-enactments, and "
        "regulations made under it; "
        "(e) where a word or expression is defined, other grammatical forms of that "
        "word or expression have corresponding meanings; "
        "(f) a reference to a person includes a natural person, body corporate, "
        "partnership, joint venture, association, government body, or other entity; "
        "(g) a reference to dollars or $ is a reference to Australian dollars unless "
        "otherwise specified."
    )

    # ---- Declaration of Trust ----
    pdf.add_page()
    pdf.section_heading("4", "DECLARATION OF TRUST")
    pdf.clause("4.1",
        "The Trustee declares that it holds the Trust Fund and all property "
        "acquired after the date of this Deed upon the trusts and with and "
        "subject to the powers and provisions set out in this Deed."
    )
    pdf.clause("4.2",
        "The trusts declared by this Deed shall be known as 'The Pemberton "
        "Family Trust' and the Trustee shall cause any property of the Trust "
        "to be held in the name of the Trust or the Trustee."
    )
    pdf.clause("4.3",
        "This Deed is irrevocable. The Settlor shall have no power to revoke, "
        "alter, or amend this Deed, and the Settlor shall have no interest in "
        "the Trust Fund or any income derived therefrom."
    )
    pdf.clause("4.4",
        "The Trust shall not be treated as a bare trust, resulting trust, or "
        "constructive trust. The beneficial interest in the Trust Fund shall "
        "vest only in accordance with the provisions of this Deed and any "
        "resolution made by the Trustee pursuant to this Deed."
    )

    # ---- Trust Fund ----
    pdf.section_heading("5", "TRUST FUND")
    pdf.clause("5.1",
        "The Trust Fund shall consist of: (a) the initial settlement sum of "
        "Ten Dollars ($10.00) paid by the Settlor; (b) all property at any "
        "time contributed to or acquired by the Trustee to be held upon the "
        "trusts of this Deed; (c) all income, profits, and gains arising from "
        "the investment or employment of the Trust Fund; (d) all property "
        "acquired with or derived from any of the foregoing; and (e) any "
        "other property which the Trustee accepts to hold on the trusts of "
        "this Deed."
    )
    pdf.clause("5.2",
        "The Trustee may accept additional property from any person to be held "
        "upon the trusts of this Deed, provided that the acceptance of such "
        "property does not, in the opinion of the Trustee, create any "
        "obligation or liability inconsistent with the terms of this Deed."
    )

    # ---- Powers of the Trustee (very dense -- multiple pages) ----
    pdf.add_page()
    pdf.section_heading("6", "POWERS OF THE TRUSTEE")
    pdf.body(
        "In addition to all powers conferred upon the Trustee by law, including "
        "without limitation the powers conferred by the Trustee Act 1958 (Vic), "
        "the Trustee shall have the following powers, which may be exercised in "
        "the absolute and uncontrolled discretion of the Trustee:"
    )

    powers = [
        ("6.1", "Power to Invest",
         "To invest the whole or any part of the Trust Fund in any form of "
         "investment whatsoever, whether or not authorised by law for the investment "
         "of trust funds, including but not limited to: (a) shares, stocks, "
         "debentures, notes, bonds, or other securities of any company, whether "
         "listed or unlisted, and whether incorporated in Australia or elsewhere; "
         "(b) units or interests in any managed investment scheme, whether or not "
         "registered under Chapter 5C of the Corporations Act; (c) real property "
         "of any description, whether freehold or leasehold, in Australia or "
         "elsewhere; (d) mortgages, charges, and other securities over real or "
         "personal property; (e) deposits with any bank, building society, or "
         "financial institution; (f) insurance policies, annuities, and endowment "
         "contracts; (g) options, futures, forward contracts, and other derivative "
         "instruments; (h) intellectual property rights, patents, trademarks, and "
         "copyrights; (i) cryptocurrency, digital assets, and tokenised securities; "
         "and (j) any other investment that a prudent person of business would make "
         "for the benefit of others for whom that person felt morally bound to provide."),

        ("6.2", "Power to Retain Assets",
         "To retain any asset forming part of the Trust Fund for such period as "
         "the Trustee thinks fit, notwithstanding that such asset may not be an "
         "investment authorised by law for the investment of trust funds or that "
         "such asset may represent a disproportionately large part of the Trust Fund. "
         "The Trustee shall not be liable for any loss arising from the retention of "
         "any asset in good faith."),

        ("6.3", "Power to Sell and Convert",
         "To sell, call in, convert, transpose, or otherwise deal with the whole "
         "or any part of the Trust Fund, by public auction or private treaty, on "
         "such terms and conditions as the Trustee thinks fit, and to give such "
         "warranties, representations, and indemnities in connection with any such "
         "sale as the Trustee considers appropriate."),

        ("6.4", "Power to Borrow",
         "To borrow money from any person (including any Beneficiary or any entity "
         "related to or associated with any Beneficiary) on such terms as the Trustee "
         "thinks fit, and to mortgage, charge, pledge, or otherwise encumber the whole "
         "or any part of the Trust Fund as security for any such borrowing. The power "
         "to borrow includes the power to draw, accept, make, endorse, discount, and "
         "otherwise deal with bills of exchange, promissory notes, and other negotiable "
         "instruments."),

        ("6.5", "Power to Lend",
         "To lend money to any Beneficiary or any entity in which a Beneficiary has "
         "an interest, on such terms (including interest-free terms) as the Trustee "
         "thinks fit, with or without security. The Trustee shall maintain proper "
         "records of all loans made pursuant to this power."),

        ("6.6", "Power to Guarantee",
         "To guarantee the performance of any obligation of any Beneficiary or any "
         "entity in which a Beneficiary has an interest, and to give security over "
         "the Trust Fund in support of any such guarantee."),

        ("6.7", "Power to Carry on Business",
         "To carry on or participate in any business, trade, profession, or venture "
         "of any kind, either alone or in partnership, joint venture, or other "
         "association with any person (including any Beneficiary), and to employ "
         "such persons and agents as the Trustee considers necessary for the conduct "
         "of any such business."),

        ("6.8", "Power to Acquire Real Property",
         "To acquire, hold, manage, develop, improve, lease, sublease, mortgage, "
         "sell, or otherwise deal with real property of any description, in any "
         "jurisdiction, including the power to construct buildings and improvements "
         "on any real property forming part of the Trust Fund."),

        ("6.9", "Power to Employ and Appoint",
         "To employ or appoint any person (including any Beneficiary or any entity "
         "in which a Beneficiary has an interest) as manager, agent, attorney, "
         "accountant, solicitor, banker, broker, financial planner, or other "
         "professional advisor, upon such terms as to remuneration and otherwise as "
         "the Trustee thinks fit."),

        ("6.10", "Power to Compromise and Settle",
         "To compromise, settle, or abandon any claim, dispute, or legal proceedings "
         "by or against the Trustee in its capacity as trustee of the Trust, on such "
         "terms as the Trustee thinks fit, and to submit any such dispute to "
         "arbitration or mediation."),

        ("6.11", "Power to Insure",
         "To insure the whole or any part of the Trust Fund against loss or damage "
         "by fire, theft, flood, earthquake, or other risk, and to insure against "
         "any liability that may arise in connection with the Trust Fund or the "
         "administration of the Trust."),

        ("6.12", "Power to Distribute In Specie",
         "To satisfy any entitlement of a Beneficiary by distributing assets of the "
         "Trust Fund in specie, at such value as the Trustee determines, without the "
         "need to convert such assets to cash. The Trustee may allocate specific "
         "assets to specific Beneficiaries in its absolute discretion."),
    ]

    for num, title, text in powers:
        pdf.sub_heading(num, title)
        pdf.body(text)

    # ---- Income Distribution ----
    pdf.add_page()
    pdf.section_heading("10", "DISTRIBUTION OF INCOME")
    pdf.clause("10.1",
        "The Trustee shall, on or before the Distribution Date in each Financial "
        "Year, determine how the Income of the Trust Fund for that Financial Year "
        "shall be distributed among the Beneficiaries. The Trustee may distribute "
        "the Income in equal or unequal proportions among all or any one or more "
        "of the Beneficiaries as the Trustee in its absolute discretion determines."
    )
    pdf.clause("10.2",
        "The Trustee may, by resolution made on or before the Distribution Date, "
        "set aside or appropriate the whole or any part of the Income for the "
        "benefit of any one or more of the Beneficiaries, and any Income so set "
        "aside shall be treated as having been distributed to and received by "
        "such Beneficiary or Beneficiaries."
    )
    pdf.clause("10.3",
        "To the extent that the Trustee does not, on or before the Distribution "
        "Date, make a determination regarding the distribution of Income for any "
        "Financial Year, the undistributed Income for that year shall be held on "
        "trust for the Primary Beneficiary, Marcus Edward Pemberton, absolutely."
    )
    pdf.clause("10.4",
        "The Trustee may, in its absolute discretion, apply any part of the Income "
        "for the maintenance, education, advancement, or benefit of any Beneficiary "
        "who is under a legal disability, including a minor. Such application may "
        "include payment to a parent or guardian of the Specified Beneficiary."
    )

    pdf.handwritten_note(
        "10.3 -- Default beneficiary clause reviewed. Confirmed Marcus E Pemberton "
        "is nominated. See FY2019 trustee resolution for precedent. -- S. Chen, 12/08/2019"
    )

    # ---- Capital Distribution ----
    pdf.section_heading("11", "DISTRIBUTION OF CAPITAL")
    pdf.clause("11.1",
        "The Trustee may, at any time during the Trust Period, distribute the whole "
        "or any part of the capital of the Trust Fund to or for the benefit of all "
        "or any one or more of the Beneficiaries, in such proportions and at such "
        "times as the Trustee in its absolute discretion determines."
    )
    pdf.clause("11.2",
        "The Trustee may accumulate the whole or any part of the Income for any "
        "Financial Year and add such accumulated Income to the capital of the "
        "Trust Fund."
    )

    # ---- Addition/Removal of Beneficiaries ----
    pdf.section_heading("13", "ADDITION AND REMOVAL OF BENEFICIARIES")
    pdf.clause("13.1",
        "The Trustee may, with the prior written consent of the Appointor and the "
        "Guardian, add any Eligible Person as a Beneficiary of the Trust by "
        "executing a supplementary deed or deed of variation."
    )
    pdf.clause("13.2",
        "The Trustee may, with the prior written consent of the Appointor, exclude "
        "any person from the class of Beneficiaries by executing a supplementary "
        "deed, provided that: (a) the Primary Beneficiary shall not be excluded "
        "without his written consent; (b) no exclusion shall affect any distribution "
        "already made or resolved upon; and (c) any excluded person shall be added "
        "to Schedule 3 (Excluded Persons)."
    )

    # ---- Appointment/Removal of Trustee ----
    pdf.section_heading("14", "APPOINTMENT AND REMOVAL OF TRUSTEE")
    pdf.clause("14.1",
        "The Appointor may, by instrument in writing, remove the Trustee and appoint "
        "a new Trustee (which may be a natural person or a body corporate) in its "
        "place. Any such appointment shall take effect upon the execution of a Deed "
        "of Retirement and Appointment."
    )
    pdf.clause("14.2",
        "A retiring Trustee shall execute all documents and do all things necessary "
        "to vest the Trust Fund in the new Trustee."
    )
    pdf.clause("14.3",
        "In the event that the Appointor is unable or unwilling to act, the Guardian "
        "shall have the power to appoint a new Trustee."
    )

    # ---- Amendment, Governing Law, etc. ----
    pdf.add_page()
    pdf.section_heading("20", "AMENDMENT OF DEED")
    pdf.clause("20.1",
        "Subject to Clause 20.2, the Trustee may, with the prior written consent of "
        "the Appointor, amend this Deed by supplementary deed, including to add, "
        "vary, or delete any provision of this Deed."
    )
    pdf.clause("20.2",
        "No amendment shall be made which: (a) changes the Trust from a discretionary "
        "trust to a fixed trust or unit trust; (b) confers any benefit on the Settlor; "
        "(c) extends the Trust Period beyond the maximum period permitted by law; or "
        "(d) is inconsistent with the rule against perpetuities as applicable in the "
        "State of Victoria."
    )

    pdf.section_heading("22", "VESTING")
    pdf.clause("22.1",
        "On the Vesting Date, the Trustee shall distribute the Trust Fund, together "
        "with all accumulated income and capital gains, to the Beneficiaries then "
        "living in such proportions as the Trustee in its absolute discretion "
        "determines. If the Trustee fails to make such a determination within "
        "ninety (90) days after the Vesting Date, the Trust Fund shall be distributed "
        "equally among all Beneficiaries then living."
    )

    pdf.section_heading("23", "GOVERNING LAW")
    pdf.body(
        "This Deed shall be governed by and construed in accordance with the laws of "
        "the State of Victoria, Commonwealth of Australia. The parties submit to the "
        "non-exclusive jurisdiction of the courts of Victoria and any courts empowered "
        "to hear appeals therefrom."
    )

    pdf.section_heading("24", "SEVERABILITY")
    pdf.body(
        "If any provision of this Deed is held to be invalid, illegal, or "
        "unenforceable, such provision shall be severed from this Deed and the "
        "remaining provisions shall continue in full force and effect. The parties "
        "agree that the invalid provision shall be replaced by a valid provision "
        "which achieves, to the greatest extent possible, the economic and legal "
        "objectives of the invalid provision."
    )

    pdf.section_heading("25", "NOTICES")
    pdf.body(
        "Any notice required to be given under this Deed shall be in writing and "
        "shall be deemed to have been duly given if: (a) delivered personally; "
        "(b) sent by prepaid registered post to the last known address of the "
        "recipient; or (c) sent by facsimile or email to the last known facsimile "
        "number or email address of the recipient. A notice shall be deemed to have "
        "been received: (i) if delivered personally, at the time of delivery; "
        "(ii) if sent by post, on the third Business Day after posting; (iii) if "
        "sent by facsimile, upon receipt of a transmission confirmation report; "
        "(iv) if sent by email, upon receipt of a read receipt or, in the absence "
        "thereof, 24 hours after sending."
    )

    # ---- SCHEDULE 1 -- BENEFICIARIES ----
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, "SCHEDULE 1 -- BENEFICIARIES", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)

    pdf.body(
        "The following persons and entities are Beneficiaries of the Trust for "
        "the purposes of this Deed. This Schedule may be amended in accordance "
        "with Clause 13."
    )

    pdf.sub_heading("", "PRIMARY BENEFICIARY")
    pdf.body(
        "Marcus Edward Pemberton, born 22 June 1975, of 12 Lansdowne Crescent, "
        "Toorak VIC 3142, Australian citizen, Company Director. Marcus is the "
        "founder and sole director of Pemberton Holdings Pty Ltd."
    )

    pdf.sub_heading("", "SECONDARY BENEFICIARIES")

    beneficiaries = [
        ("Sarah Louise Pemberton", "spouse of the Primary Beneficiary, of 12 "
         "Lansdowne Crescent, Toorak VIC 3142, Australian citizen, Medical "
         "Practitioner, born 15 January 1978"),
        ("Rebecca Anne Pemberton", "sister of the Primary Beneficiary, of "
         "45 Brighton Road, St Kilda VIC 3182, Australian citizen, Architect, "
         "born 3 March 1980"),
        ("Thomas James Pemberton", "son of the Primary Beneficiary, of "
         "12 Lansdowne Crescent, Toorak VIC 3142, Australian citizen, Student, "
         "born 14 August 2005"),
        ("Emily Grace Pemberton", "daughter of the Primary Beneficiary, of "
         "12 Lansdowne Crescent, Toorak VIC 3142, Australian citizen, Student, "
         "born 29 November 2008"),
        ("Dorothy May Pemberton", "mother of the Primary Beneficiary, of "
         "22 Beach Road, Mentone VIC 3194, Australian citizen, Retired School "
         "Teacher, born 7 April 1948"),
    ]

    for i, (name, desc) in enumerate(beneficiaries, 1):
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(8, 5.5, f"{i}.")
        pdf.cell(55, 5.5, name)
        pdf.set_font("Helvetica", "", 10)
        pdf.multi_cell(0, 5.5, f" -- {desc}.")
        pdf.ln(2)

    pdf.sub_heading("", "CORPORATE BENEFICIARY")
    pdf.body(
        "Pemberton Capital Group Pty Ltd (ACN 641 028 495), a company incorporated "
        "in the State of Victoria, having its registered office at Unit 7, 34 Chapel "
        "Street, South Yarra VIC 3141. This company is wholly owned by Marcus Edward "
        "Pemberton."
    )

    pdf.handwritten_note(
        "Schedule 1 amended by Variation Deed dated 22/03/2021 -- see attached. "
        "Rebecca Anne Pemberton REMOVED (Clause 2.1 of Variation). "
        "New beneficiary ADDED: see Variation Deed. -- M. Henderson, 22/03/2021"
    )

    # ---- SCHEDULE 2 -- Initial Property ----
    pdf.ln(5)
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, "SCHEDULE 2 -- INITIAL TRUST PROPERTY", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)
    pdf.body(
        "The sum of Ten Dollars ($10.00) paid by the Settlor, Geoffrey Alan "
        "Henderson, to the Trustee, Pemberton Holdings Pty Ltd, upon the execution "
        "of this Deed."
    )

    # ---- SCHEDULE 3 -- Excluded Persons ----
    pdf.ln(5)
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, "SCHEDULE 3 -- EXCLUDED PERSONS", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)
    pdf.body("As at the date of this Deed, there are no Excluded Persons.")
    pdf.handwritten_note(
        "Updated 22/03/2021: Rebecca Anne Pemberton added to Schedule 3 "
        "per Variation Deed. -- M. Henderson"
    )

    # ---- Execution ----
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, "EXECUTION", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(8)
    pdf.body("Executed as a Deed on the 8th day of November 2017.")

    for signer, role, title in [
        ("Geoffrey Alan Henderson", "SETTLOR", "Solicitor"),
        ("Marcus Edward Pemberton", "APPOINTOR and sole Director of PEMBERTON HOLDINGS PTY LTD", "Director"),
        ("Sarah Louise Pemberton", "GUARDIAN", "Medical Practitioner"),
    ]:
        pdf.ln(8)
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(0, 6, f"SIGNED, SEALED AND DELIVERED by {signer}", new_x="LMARGIN", new_y="NEXT")
        pdf.cell(0, 6, f"in the capacity of {role}:", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(12)
        pdf.line(15, pdf.get_y(), 85, pdf.get_y())
        pdf.ln(2)
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(0, 5, f"{signer}", new_x="LMARGIN", new_y="NEXT")
        pdf.cell(0, 5, title, new_x="LMARGIN", new_y="NEXT")

    pdf.stamp("CERTIFIED TRUE COPY -- Henderson Chambers & Partners -- 8/11/2017")
    pdf.scan_artifact()


def add_variation_deed_1(pdf: TrustBundlePDF):
    """Variation Deed 1 (March 2021): Removes Rebecca, adds Vladimir Ivanovich Petrov."""
    pdf.separator_page(
        "VARIATION DEED NO. 1",
        "Dated 22 March 2021"
    )
    pdf.set_doc_title("VARIATION DEED NO. 1 -- dated 22 March 2021")

    pdf.add_page()
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 12, "DEED OF VARIATION", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, "THE PEMBERTON FAMILY TRUST", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)
    pdf.set_font("Helvetica", "", 11)
    pdf.cell(0, 8, "Variation Deed No. 1", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 8, "Date: 22 March 2021", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(8)

    pdf.section_heading("1", "PARTIES TO THIS VARIATION")
    pdf.body(
        "This Deed of Variation is made on the 22nd day of March 2021 between:"
    )
    pdf.clause("1.1",
        "Pemberton Holdings Pty Ltd (ACN 618 492 713), in its capacity as Trustee "
        "of The Pemberton Family Trust ('the Trustee');"
    )
    pdf.clause("1.2",
        "Marcus Edward Pemberton, in his capacity as Appointor of The Pemberton "
        "Family Trust ('the Appointor');"
    )
    pdf.clause("1.3",
        "Sarah Louise Pemberton, in her capacity as Guardian of The Pemberton "
        "Family Trust ('the Guardian')."
    )

    pdf.section_heading("2", "VARIATIONS")
    pdf.body(
        "Pursuant to Clause 13 and Clause 20 of the Original Deed dated "
        "8 November 2017, the parties agree to the following variations:"
    )

    pdf.sub_heading("2.1", "REMOVAL OF BENEFICIARY")
    pdf.body(
        "Rebecca Anne Pemberton (sister of the Primary Beneficiary) is hereby "
        "removed from Schedule 1 as a Secondary Beneficiary and is added to "
        "Schedule 3 (Excluded Persons) of the Original Deed, effective from "
        "the date of this Variation Deed."
    )
    pdf.handwritten_note(
        "Reason for removal: Family dispute following divorce proceedings "
        "of Rebecca from Marcus's business partner (David Chen). Rebecca "
        "consented in writing -- see attached consent letter dated 15/03/2021. "
        "-- G. Henderson"
    )

    pdf.sub_heading("2.2", "ADDITION OF BENEFICIARY")
    pdf.body(
        "The following person is hereby added to Schedule 1 as a Secondary "
        "Beneficiary of the Trust:"
    )
    pdf.body(
        "Vladimir Ivanovich Petrov, born 3 September 1982, of Apartment 14B, "
        "28 Southbank Boulevard, Southbank VIC 3006, Russian Federation citizen "
        "holding Australian Permanent Residency (Visa Subclass 186), Business "
        "Consultant. Mr Petrov is a long-standing business associate of the "
        "Primary Beneficiary and has provided substantial consulting services "
        "to Pemberton Capital Group Pty Ltd since 2018."
    )

    pdf.handwritten_note(
        "COMPLIANCE NOTE: Vladimir Petrov -- Foreign national (Russia). "
        "Enhanced CDD conducted. DFAT sanctions check performed 18/03/2021 "
        "-- no match found. ATO FIRB notification not required (no real "
        "property distribution anticipated). Passport copy and visa attached. "
        "-- S. Chen, Compliance Officer"
    )

    pdf.body(
        "The Trustee, Appointor, and Guardian have each consented to the "
        "addition of Mr Petrov as a Beneficiary in accordance with Clause 13.1 "
        "of the Original Deed."
    )

    pdf.section_heading("3", "CONFIRMATION")
    pdf.body(
        "Save as varied by this Deed, the Original Deed and all previous "
        "variations (if any) remain in full force and effect. In the event of "
        "any inconsistency between this Deed and the Original Deed, the "
        "provisions of this Deed shall prevail."
    )

    # Execution
    pdf.ln(5)
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, "EXECUTION", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)
    pdf.body("Executed as a Deed on the 22nd day of March 2021.")

    for signer, role in [
        ("Marcus Edward Pemberton", "Sole Director, Pemberton Holdings Pty Ltd (Trustee)"),
        ("Marcus Edward Pemberton", "Appointor"),
        ("Sarah Louise Pemberton", "Guardian"),
    ]:
        pdf.ln(6)
        pdf.line(15, pdf.get_y(), 75, pdf.get_y())
        pdf.ln(2)
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(0, 5, signer, new_x="LMARGIN", new_y="NEXT")
        pdf.cell(0, 5, role, new_x="LMARGIN", new_y="NEXT")

    pdf.stamp("CERTIFIED TRUE COPY -- Henderson Chambers & Partners -- 22/03/2021")


def add_variation_deed_2(pdf: TrustBundlePDF):
    """Variation Deed 2 (June 2023): Adds foreign corporate beneficiaries."""
    pdf.separator_page(
        "VARIATION DEED NO. 2",
        "Dated 14 June 2023"
    )
    pdf.set_doc_title("VARIATION DEED NO. 2 -- dated 14 June 2023")

    pdf.add_page()
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 12, "DEED OF VARIATION", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, "THE PEMBERTON FAMILY TRUST", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)
    pdf.set_font("Helvetica", "", 11)
    pdf.cell(0, 8, "Variation Deed No. 2 -- International Expansion", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 8, "Date: 14 June 2023", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(8)

    pdf.section_heading("1", "BACKGROUND")
    pdf.body(
        "The Trustee wishes to add certain corporate entities as Beneficiaries "
        "of the Trust to facilitate the international business activities of the "
        "Pemberton family. The Appointor and Guardian have given their prior "
        "written consent in accordance with Clause 13.1 of the Original Deed."
    )

    pdf.section_heading("2", "ADDITION OF CORPORATE BENEFICIARIES")

    pdf.sub_heading("2.1", "SINGAPORE ENTITY")
    pdf.body(
        "Eastbridge Holdings Pte Ltd, a company incorporated in the Republic "
        "of Singapore under registration number 202318742G, having its registered "
        "office at 80 Robinson Road, #02-00, Singapore 068898. This entity is a "
        "wholly-owned subsidiary of Pemberton Capital Group Pty Ltd. Director: "
        "Marcus Edward Pemberton."
    )

    pdf.sub_heading("2.2", "HONG KONG ENTITY")
    pdf.body(
        "Pemberton-Chen International Limited, a company incorporated in the "
        "Hong Kong Special Administrative Region under company number 3148926, "
        "having its registered office at Suite 2201, Two IFC, 8 Finance Street, "
        "Central, Hong Kong. This entity is a joint venture between Pemberton "
        "Capital Group Pty Ltd (60% shareholding) and Chen Family Holdings Ltd "
        "(40% shareholding). Directors: Marcus Edward Pemberton and David Wei Chen."
    )

    pdf.handwritten_note(
        "ELEVATED RISK: Two foreign corporate beneficiaries added. "
        "Singapore and Hong Kong jurisdictions. Enhanced Due Diligence "
        "required per AML/CTF Rules Ch. 15. FIRB implications reviewed -- "
        "no real property currently held by trust. Will need ongoing "
        "monitoring. -- Henderson Chambers, 14/06/2023"
    )

    pdf.section_heading("3", "RISK ACKNOWLEDGEMENT")
    pdf.body(
        "The parties acknowledge that the addition of foreign corporate "
        "Beneficiaries may trigger additional reporting obligations under the "
        "Anti-Money Laundering and Counter-Terrorism Financing Act 2006 (Cth) "
        "and the Foreign Acquisitions and Takeovers Act 1975 (Cth). The Trustee "
        "undertakes to comply with all applicable reporting obligations."
    )

    # Execution
    pdf.ln(5)
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, "EXECUTION", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.body("Executed as a Deed on the 14th day of June 2023.")

    for signer, role in [
        ("Marcus Edward Pemberton", "Sole Director, Pemberton Holdings Pty Ltd (Trustee)"),
        ("Marcus Edward Pemberton", "Appointor"),
        ("Sarah Louise Pemberton", "Guardian"),
    ]:
        pdf.ln(6)
        pdf.line(15, pdf.get_y(), 75, pdf.get_y())
        pdf.ln(2)
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(0, 5, signer, new_x="LMARGIN", new_y="NEXT")
        pdf.cell(0, 5, role, new_x="LMARGIN", new_y="NEXT")

    pdf.stamp("CERTIFIED TRUE COPY -- Henderson Chambers & Partners -- 14/06/2023")
    pdf.scan_artifact()


def add_trustee_change(pdf: TrustBundlePDF):
    """Deed of Retirement and Appointment (Feb 2024): Changes trustee."""
    pdf.separator_page(
        "DEED OF RETIREMENT AND APPOINTMENT OF TRUSTEE",
        "Dated 1 February 2024"
    )
    pdf.set_doc_title("DEED OF RETIREMENT AND APPOINTMENT -- dated 1 February 2024")

    pdf.add_page()
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 12, "DEED OF RETIREMENT AND APPOINTMENT", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, "THE PEMBERTON FAMILY TRUST", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)
    pdf.set_font("Helvetica", "", 11)
    pdf.cell(0, 8, "Date: 1 February 2024", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(8)

    pdf.section_heading("1", "PARTIES")
    pdf.clause("1.1",
        "Pemberton Holdings Pty Ltd (ACN 618 492 713), the Retiring Trustee;"
    )
    pdf.clause("1.2",
        "Pemberton Advisory Pty Ltd (ACN 672 831 059), a company incorporated "
        "in the State of Victoria, having its registered office at Level 3, "
        "500 Bourke Street, Melbourne VIC 3000, the Incoming Trustee;"
    )
    pdf.clause("1.3",
        "Marcus Edward Pemberton, in his capacity as Appointor."
    )

    pdf.section_heading("2", "RECITALS")
    pdf.clause("A",
        "The Appointor has resolved, pursuant to Clause 14.1 of the Original "
        "Deed dated 8 November 2017, to remove Pemberton Holdings Pty Ltd as "
        "Trustee and to appoint Pemberton Advisory Pty Ltd in its place."
    )
    pdf.clause("B",
        "The directors of Pemberton Advisory Pty Ltd are Marcus Edward Pemberton "
        "and Sarah Louise Pemberton. The company secretary is Sarah Louise Pemberton."
    )

    pdf.section_heading("3", "OPERATIVE PROVISIONS")
    pdf.clause("3.1",
        "Pemberton Holdings Pty Ltd hereby retires as Trustee of The Pemberton "
        "Family Trust with effect from the date of this Deed."
    )
    pdf.clause("3.2",
        "Pemberton Advisory Pty Ltd is hereby appointed as Trustee of The "
        "Pemberton Family Trust with effect from the date of this Deed."
    )
    pdf.clause("3.3",
        "The Retiring Trustee hereby transfers and vests all Trust property "
        "in the Incoming Trustee."
    )
    pdf.clause("3.4",
        "The Incoming Trustee acknowledges that it has received a copy of the "
        "Original Deed and all Variation Deeds and undertakes to comply with "
        "all obligations imposed on the Trustee thereunder."
    )

    pdf.handwritten_note(
        "Reason for change: Pemberton Holdings being wound up as part of "
        "corporate restructure. All assets transferred. ASIC change of "
        "officeholder forms lodged 3/02/2024. -- G. Henderson"
    )

    # Execution
    pdf.ln(5)
    for signer, role in [
        ("Marcus Edward Pemberton", "Director, Pemberton Holdings Pty Ltd (Retiring Trustee)"),
        ("Marcus Edward Pemberton", "Director, Pemberton Advisory Pty Ltd (Incoming Trustee)"),
        ("Sarah Louise Pemberton", "Director/Secretary, Pemberton Advisory Pty Ltd"),
        ("Marcus Edward Pemberton", "Appointor"),
    ]:
        pdf.ln(6)
        pdf.line(15, pdf.get_y(), 75, pdf.get_y())
        pdf.ln(2)
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(0, 5, signer, new_x="LMARGIN", new_y="NEXT")
        pdf.cell(0, 5, role, new_x="LMARGIN", new_y="NEXT")

    pdf.stamp("CERTIFIED TRUE COPY -- Henderson Chambers & Partners -- 01/02/2024")


def add_asic_extracts(pdf: TrustBundlePDF):
    """Simulated ASIC company extracts for both trustee companies."""
    pdf.separator_page("ASIC COMPANY EXTRACTS", "Retrieved 15 March 2024")
    pdf.set_doc_title("ASIC Company Extract")

    for company, acn, status, directors, reg_date in [
        ("PEMBERTON HOLDINGS PTY LTD", "618 492 713", "Deregistered (voluntary) -- 28/02/2024",
         [("Marcus Edward Pemberton", "Director/Secretary", "08/11/2017", "28/02/2024")],
         "03/08/2017"),
        ("PEMBERTON ADVISORY PTY LTD", "672 831 059", "Registered",
         [("Marcus Edward Pemberton", "Director", "15/01/2024", "Current"),
          ("Sarah Louise Pemberton", "Director/Secretary", "15/01/2024", "Current")],
         "15/01/2024"),
        ("PEMBERTON CAPITAL GROUP PTY LTD", "641 028 495", "Registered",
         [("Marcus Edward Pemberton", "Director/Secretary", "12/06/2019", "Current")],
         "12/06/2019"),
    ]:
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(0, 6, "AUSTRALIAN SECURITIES AND INVESTMENTS COMMISSION", align="C", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "B", 14)
        pdf.cell(0, 10, "COMPANY EXTRACT", align="C", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(5)

        fields = [
            ("Company Name:", company),
            ("ACN:", acn),
            ("ABN:", f"-- See ABR for ABN details"),
            ("Type:", "Australian Proprietary Company, Limited By Shares"),
            ("Status:", status),
            ("Registration Date:", reg_date),
            ("Registered Office:", "Level 3, 500 Bourke Street, Melbourne VIC 3000" if "ADVISORY" in company
             else "Unit 7, 34 Chapel Street, South Yarra VIC 3141"),
            ("Principal Place of Business:", "As above"),
        ]

        for label, value in fields:
            pdf.set_font("Helvetica", "B", 10)
            pdf.cell(55, 6, label)
            pdf.set_font("Helvetica", "", 10)
            pdf.cell(0, 6, value, new_x="LMARGIN", new_y="NEXT")

        pdf.ln(5)
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, "OFFICEHOLDERS", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)

        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(55, 6, "Name")
        pdf.cell(40, 6, "Position")
        pdf.cell(30, 6, "Appointed")
        pdf.cell(30, 6, "Ceased", new_x="LMARGIN", new_y="NEXT")
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(1)

        pdf.set_font("Helvetica", "", 9)
        for name, pos, start, end in directors:
            pdf.cell(55, 6, name)
            pdf.cell(40, 6, pos)
            pdf.cell(30, 6, start)
            pdf.cell(30, 6, end, new_x="LMARGIN", new_y="NEXT")

        pdf.ln(5)
        pdf.set_font("Helvetica", "I", 8)
        pdf.cell(0, 5, "This extract was produced from ASIC's database on 15/03/2024 at 14:22:07 AEST",
                 new_x="LMARGIN", new_y="NEXT")
        pdf.cell(0, 5, "Data is current as at the date and time of production.",
                 new_x="LMARGIN", new_y="NEXT")
        pdf.scan_artifact()


def add_meeting_minutes(pdf: TrustBundlePDF):
    """Trustee meeting minutes -- resolutions for distributions and variations."""
    pdf.separator_page("TRUSTEE MEETING MINUTES", "Financial Years 2018-2024")
    pdf.set_doc_title("Trustee Meeting Minutes")

    minutes_data = [
        ("28 June 2019", "FY2019 Income Distribution Resolution",
         ["Marcus Edward Pemberton (Director, Pemberton Holdings Pty Ltd)"],
         [
             "RESOLVED that the net income of The Pemberton Family Trust for the "
             "financial year ending 30 June 2019 be distributed as follows:",
             "  - Marcus Edward Pemberton: 40%",
             "  - Sarah Louise Pemberton: 30%",
             "  - Thomas James Pemberton: 10%",
             "  - Emily Grace Pemberton: 10%",
             "  - Dorothy May Pemberton: 10%",
             "RESOLVED that undistributed income, if any, shall be accumulated and "
             "added to the capital of the Trust Fund.",
         ]),
        ("27 June 2020", "FY2020 Income Distribution Resolution",
         ["Marcus Edward Pemberton (Director, Pemberton Holdings Pty Ltd)"],
         [
             "RESOLVED that the net income for FY2020 be distributed as follows:",
             "  - Marcus Edward Pemberton: 35%",
             "  - Sarah Louise Pemberton: 25%",
             "  - Pemberton Capital Group Pty Ltd: 20%",
             "  - Thomas James Pemberton: 10%",
             "  - Emily Grace Pemberton: 10%",
             "NOTE: Rebecca Anne Pemberton received 0% distribution. No objection recorded.",
         ]),
        ("22 March 2021", "Special Resolution -- Variation of Beneficiaries",
         ["Marcus Edward Pemberton (Director, Pemberton Holdings Pty Ltd)"],
         [
             "RESOLVED that Rebecca Anne Pemberton be removed as a Beneficiary of "
             "the Trust in accordance with Clause 13.2 of the Deed.",
             "RESOLVED that Vladimir Ivanovich Petrov be added as a Secondary "
             "Beneficiary in accordance with Clause 13.1 of the Deed.",
             "NOTED that the Appointor and Guardian have provided written consent.",
             "NOTED that DFAT sanctions screening has been conducted for Mr Petrov "
             "with no adverse findings as at 18/03/2021.",
         ]),
        ("14 June 2023", "Special Resolution -- International Corporate Beneficiaries",
         ["Marcus Edward Pemberton (Director, Pemberton Holdings Pty Ltd)"],
         [
             "RESOLVED to add Eastbridge Holdings Pte Ltd (Singapore) and "
             "Pemberton-Chen International Limited (Hong Kong) as Corporate "
             "Beneficiaries of the Trust.",
             "NOTED that Enhanced Due Diligence has been conducted on both entities.",
             "NOTED that ongoing DFAT sanctions monitoring will be required for the "
             "foreign entities and their directors.",
         ]),
        ("29 June 2024", "FY2024 Income Distribution Resolution",
         ["Marcus Edward Pemberton (Director, Pemberton Advisory Pty Ltd)",
          "Sarah Louise Pemberton (Director/Secretary, Pemberton Advisory Pty Ltd)"],
         [
             "RESOLVED that the net income for FY2024 be distributed as follows:",
             "  - Marcus Edward Pemberton: 25%",
             "  - Sarah Louise Pemberton: 20%",
             "  - Vladimir Ivanovich Petrov: 15%",
             "  - Pemberton Capital Group Pty Ltd: 15%",
             "  - Eastbridge Holdings Pte Ltd: 10%",
             "  - Thomas James Pemberton: 5%",
             "  - Emily Grace Pemberton: 5%",
             "  - Dorothy May Pemberton: 5%",
         ]),
    ]

    for date, title, attendees, resolutions in minutes_data:
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 14)
        pdf.cell(0, 10, "MINUTES OF MEETING OF THE TRUSTEE", align="C", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, "THE PEMBERTON FAMILY TRUST", align="C", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(5)

        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(30, 6, "Date:")
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(0, 6, date, new_x="LMARGIN", new_y="NEXT")

        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(30, 6, "Subject:")
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(0, 6, title, new_x="LMARGIN", new_y="NEXT")

        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(30, 6, "Present:")
        pdf.set_font("Helvetica", "", 10)
        for att in attendees:
            pdf.cell(0, 6, att, new_x="LMARGIN", new_y="NEXT")
            pdf.cell(30, 6, "")
        pdf.ln(5)

        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(0, 7, "RESOLUTIONS:", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(3)

        pdf.set_font("Helvetica", "", 10)
        for res in resolutions:
            pdf.multi_cell(0, 5.5, res)
            pdf.ln(1)

        pdf.ln(5)
        pdf.line(15, pdf.get_y(), 75, pdf.get_y())
        pdf.ln(2)
        pdf.set_font("Helvetica", "", 9)
        pdf.cell(0, 5, "Signed: Marcus Edward Pemberton", new_x="LMARGIN", new_y="NEXT")
        pdf.cell(0, 5, f"Date: {date}", new_x="LMARGIN", new_y="NEXT")

        if random.random() > 0.5:
            pdf.scan_artifact()


def add_solicitor_correspondence(pdf: TrustBundlePDF):
    """Solicitor letters and file notes."""
    pdf.separator_page("SOLICITOR CORRESPONDENCE", "Henderson Chambers & Partners")
    pdf.set_doc_title("Solicitor Correspondence")

    letters = [
        ("8 November 2017", "Partner Reference: HCP/MXP/2017/4481",
         "Dear Marcus,\n\n"
         "I enclose herewith the executed Trust Deed for The Pemberton Family Trust. "
         "Please retain this document in a secure location as it constitutes the "
         "governing instrument of the Trust.\n\n"
         "Key points to note:\n"
         "1. The Vesting Date is 8 November 2097 (80 years from settlement).\n"
         "2. You are named as both Appointor and sole director of the Trustee.\n"
         "3. Sarah is named as Guardian with oversight powers.\n"
         "4. Annual distribution resolutions must be made before 30 June each year.\n"
         "5. Any amendments require a formal Deed of Variation.\n\n"
         "Please do not hesitate to contact me should you have any queries.\n\n"
         "Yours faithfully,\n"
         "Geoffrey Alan Henderson\n"
         "Partner"),

        ("15 March 2021", "Partner Reference: HCP/MXP/2021/0892",
         "Dear Marcus,\n\n"
         "Further to our telephone discussion of 10 March 2021, I confirm that we "
         "have prepared the Deed of Variation to: (a) remove Rebecca from the class "
         "of Beneficiaries; and (b) add Mr Vladimir Ivanovich Petrov as a Secondary "
         "Beneficiary.\n\n"
         "I note that Mr Petrov is a citizen of the Russian Federation holding "
         "Australian permanent residency. While this does not of itself give rise to "
         "any legal impediment to his inclusion as a Beneficiary, I strongly recommend "
         "that the Trustee conduct Enhanced Customer Due Diligence in respect of "
         "Mr Petrov, including verification of his identity, source of wealth, and "
         "ongoing DFAT sanctions monitoring.\n\n"
         "The executed Variation Deed is enclosed.\n\n"
         "Yours faithfully,\n"
         "Geoffrey Alan Henderson\n"
         "Partner"),

        ("20 June 2023", "Partner Reference: HCP/MXP/2023/2147",
         "PRIVILEGED AND CONFIDENTIAL\n\n"
         "Dear Marcus,\n\n"
         "Re: Addition of Foreign Corporate Beneficiaries\n\n"
         "I refer to the Variation Deed No. 2 executed on 14 June 2023 adding "
         "Eastbridge Holdings Pte Ltd (Singapore) and Pemberton-Chen International "
         "Limited (Hong Kong) as corporate Beneficiaries.\n\n"
         "I must draw your attention to the following compliance considerations:\n\n"
         "1. AUSTRAC REPORTING: The Trust now has foreign corporate beneficiaries. "
         "Any reporting entity dealing with the Trust should be aware that Enhanced "
         "Customer Due Diligence (ECDD) may be required under the AML/CTF Act.\n\n"
         "2. FIRB: If the Trust acquires any interest in Australian land (including "
         "commercial property), Foreign Investment Review Board approval may be "
         "required given the foreign beneficial ownership.\n\n"
         "3. CRS/FATCA: The Trust may now have Common Reporting Standard (CRS) and "
         "Foreign Account Tax Compliance Act (FATCA) reporting obligations.\n\n"
         "4. TRANSFER PRICING: Any transactions between the Trust and the foreign "
         "entities must be at arm's length.\n\n"
         "I recommend that you discuss these matters with your accountant.\n\n"
         "Yours faithfully,\n"
         "Geoffrey Alan Henderson\n"
         "Partner"),
    ]

    for date, ref, body in letters:
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, "HENDERSON CHAMBERS & PARTNERS", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 9)
        pdf.cell(0, 5, "Barristers, Solicitors & Notaries Public", new_x="LMARGIN", new_y="NEXT")
        pdf.cell(0, 5, "Level 18, 101 Collins Street, Melbourne VIC 3000", new_x="LMARGIN", new_y="NEXT")
        pdf.cell(0, 5, "T: (03) 9654 2200  F: (03) 9654 2201  E: mail@hendersonchambers.com.au", new_x="LMARGIN", new_y="NEXT")
        pdf.line(10, pdf.get_y() + 2, 200, pdf.get_y() + 2)
        pdf.ln(8)

        pdf.set_font("Helvetica", "", 10)
        pdf.cell(0, 6, date, new_x="LMARGIN", new_y="NEXT")
        pdf.cell(0, 6, ref, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(3)
        pdf.cell(0, 6, "Mr Marcus Pemberton", new_x="LMARGIN", new_y="NEXT")
        pdf.cell(0, 6, "12 Lansdowne Crescent", new_x="LMARGIN", new_y="NEXT")
        pdf.cell(0, 6, "Toorak VIC 3142", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(5)

        pdf.set_font("Helvetica", "", 10)
        for para in body.split("\n"):
            if para.strip():
                pdf.multi_cell(0, 5.5, para)
            pdf.ln(2)

        pdf.scan_artifact()


def add_id_documents(pdf: TrustBundlePDF):
    """Simulated certified identity document pages."""
    pdf.separator_page("CERTIFIED IDENTITY DOCUMENTS", "Sighted and certified copies")
    pdf.set_doc_title("Certified Identity Documents")

    persons = [
        ("Marcus Edward Pemberton", "Australian Passport", "PA4821937", "22/06/1975", "Australian"),
        ("Sarah Louise Pemberton", "Australian Passport", "PA5193648", "15/01/1978", "Australian"),
        ("Vladimir Ivanovich Petrov", "Russian Federation Passport", "72 4819326", "03/09/1982", "Russian Federation"),
        ("Vladimir Ivanovich Petrov", "Australian Visa Grant (Subclass 186)", "VEVO: 1051824793", "03/09/1982", "N/A"),
    ]

    for name, doc_type, doc_num, dob, nationality in persons:
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 14)
        pdf.cell(0, 10, "CERTIFIED COPY OF IDENTITY DOCUMENT", align="C", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(10)

        fields = [
            ("Full Name:", name),
            ("Document Type:", doc_type),
            ("Document Number:", doc_num),
            ("Date of Birth:", dob),
            ("Nationality:", nationality),
        ]

        for label, value in fields:
            pdf.set_font("Helvetica", "B", 11)
            pdf.cell(50, 7, label)
            pdf.set_font("Helvetica", "", 11)
            pdf.cell(0, 7, value, new_x="LMARGIN", new_y="NEXT")

        pdf.ln(10)
        pdf.set_font("Helvetica", "I", 10)
        pdf.multi_cell(0, 6,
            "[PLACEHOLDER: In a real compliance bundle, this page would contain "
            "a scanned copy of the identity document. The actual document has been "
            "sighted and certified by an authorised person.]"
        )

        pdf.ln(10)
        pdf.stamp(f"CERTIFIED TRUE COPY -- Original sighted by G. Henderson, Solicitor")

        pdf.ln(5)
        pdf.handwritten_note(
            f"Identity verified: {name}. Photo ID matches person presenting. "
            f"Original document sighted and returned. -- G. Henderson"
        )
        pdf.scan_artifact()


def add_stamp_duty(pdf: TrustBundlePDF):
    """Stamp duty assessment and receipt pages."""
    pdf.separator_page("STAMP DUTY DOCUMENTATION", "State Revenue Office Victoria")
    pdf.set_doc_title("Stamp Duty Assessment")

    pdf.add_page()
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, "STATE REVENUE OFFICE", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "DUTIES ACT 2000 (VIC)", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 8, "ASSESSMENT OF DUTY -- DECLARATION OF TRUST", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(10)

    fields = [
        ("Assessment Number:", "SRO/2017/DT/482917"),
        ("Date of Assessment:", "15 November 2017"),
        ("Instrument:", "Deed of Trust -- The Pemberton Family Trust"),
        ("Date of Instrument:", "8 November 2017"),
        ("Dutiable Value:", "$10.00 (initial settlement sum)"),
        ("Duty Assessed:", "$200.00 (nominal duty on declaration of trust)"),
        ("Status:", "PAID -- Receipt No. 7284910"),
    ]

    for label, value in fields:
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(50, 7, label)
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(0, 7, value, new_x="LMARGIN", new_y="NEXT")

    pdf.ln(10)
    pdf.stamp("STAMP DUTY PAID -- State Revenue Office Victoria -- $200.00")
    pdf.scan_artifact()


def add_filler_pages(pdf: TrustBundlePDF, target_pages: int):
    """Adds additional boilerplate pages to reach the target page count."""
    pdf.set_doc_title("THE PEMBERTON FAMILY TRUST -- Supplementary Documentation")

    # Additional legal opinions, compliance checklists, etc.
    filler_sections = [
        ("COMPLIANCE CHECKLIST -- AML/CTF ACT 2006",
         [
             "Item 1: Customer Identification Procedure (CIP) completed for all "
             "beneficial owners holding 25% or more of the Trust -- COMPLETE",
             "Item 2: Verification of identity for all natural person beneficiaries "
             "using primary photographic identification -- COMPLETE",
             "Item 3: DFAT Consolidated Sanctions List screening for all beneficiaries "
             "and officeholders -- COMPLETE (last screened: 15/03/2024)",
             "Item 4: Politically Exposed Person (PEP) screening -- COMPLETE (no matches)",
             "Item 5: Source of Wealth verification for Primary Beneficiary -- COMPLETE",
             "Item 6: Enhanced Customer Due Diligence for foreign national beneficiary "
             "(Vladimir Ivanovich Petrov) -- COMPLETE",
             "Item 7: Enhanced Customer Due Diligence for foreign corporate beneficiaries "
             "(Eastbridge Holdings Pte Ltd, Pemberton-Chen International Limited) -- COMPLETE",
             "Item 8: Ongoing monitoring plan established -- COMPLETE",
             "Item 9: Risk assessment completed (overall risk rating: MEDIUM-HIGH due to "
             "foreign corporate beneficiaries and foreign national beneficiary) -- COMPLETE",
             "Item 10: Record retention plan (7 years post-relationship) -- NOTED",
         ]),
        ("BENEFICIAL OWNERSHIP SUMMARY -- CURRENT AS AT 15 MARCH 2024",
         [
             "The following is a summary of the current beneficial ownership structure "
             "of The Pemberton Family Trust, incorporating all variations to date:",
             "",
             "TRUST NAME: The Pemberton Family Trust",
             "ABN: 53 714 289 301",
             "CURRENT TRUSTEE: Pemberton Advisory Pty Ltd (ACN 672 831 059)",
             "APPOINTOR: Marcus Edward Pemberton",
             "GUARDIAN: Sarah Louise Pemberton",
             "",
             "CURRENT BENEFICIARIES (as at 15 March 2024):",
             "1. Marcus Edward Pemberton (Primary Beneficiary) -- Australian citizen",
             "2. Sarah Louise Pemberton -- Australian citizen",
             "3. Thomas James Pemberton -- Australian citizen (minor)",
             "4. Emily Grace Pemberton -- Australian citizen (minor)",
             "5. Dorothy May Pemberton -- Australian citizen",
             "6. Vladimir Ivanovich Petrov -- Russian Federation citizen, AU PR",
             "7. Pemberton Capital Group Pty Ltd (ACN 641 028 495) -- Australian company",
             "8. Eastbridge Holdings Pte Ltd (Reg. 202318742G) -- Singapore company",
             "9. Pemberton-Chen International Limited (Co. 3148926) -- Hong Kong company",
             "",
             "EXCLUDED PERSONS (Schedule 3):",
             "1. Rebecca Anne Pemberton -- excluded per Variation Deed No. 1 (22/03/2021)",
             "",
             "RISK INDICATORS:",
             "- Foreign national beneficiary (Russian Federation)",
             "- Two foreign corporate beneficiaries (Singapore, Hong Kong)",
             "- Complex multi-jurisdictional structure",
             "- Joint venture with non-family entity (Chen Family Holdings Ltd -- 40% of HK entity)",
             "",
             "OVERALL AML RISK RATING: MEDIUM-HIGH",
         ]),
        ("ACCOUNTANT'S CERTIFICATE -- ANNUAL COMPLIANCE",
         [
             "TO WHOM IT MAY CONCERN",
             "",
             "We, Parker & Associates Chartered Accountants, confirm that we have "
             "prepared the financial statements and tax returns for The Pemberton "
             "Family Trust (ABN 53 714 289 301) for the financial year ended "
             "30 June 2024.",
             "",
             "We confirm that:",
             "1. The Trust's income has been distributed in accordance with the "
             "   Trustee's resolution dated 29 June 2024.",
             "2. The Trust's tax return has been lodged with the Australian Taxation "
             "   Office.",
             "3. All beneficiaries who received distributions have been issued with "
             "   distribution statements.",
             "4. The Trust has complied with Division 6 of Part III of the Income "
             "   Tax Assessment Act 1936 (Cth).",
             "",
             "This certificate is issued for compliance purposes only and does not "
             "constitute an audit opinion.",
             "",
             "Parker & Associates",
             "Chartered Accountants",
             "Level 8, 440 Collins Street, Melbourne VIC 3000",
             "Date: 30 September 2024",
         ]),
        ("FILE NOTE -- ONGOING MONITORING",
         [
             "DATE: 15 March 2024",
             "FILE: The Pemberton Family Trust",
             "AUTHOR: Sandra Chen, Compliance Officer",
             "",
             "Annual AML/CTF monitoring review conducted. Key findings:",
             "",
             "1. DFAT SANCTIONS SCREENING:",
             "   All 9 current beneficiaries and 3 officeholders screened against "
             "   the DFAT Consolidated Sanctions List (downloaded 15/03/2024).",
             "   Result: NO MATCHES FOUND.",
             "",
             "   Special attention given to Vladimir Ivanovich Petrov due to "
             "   Russian Federation citizenship. Cross-referenced against:",
             "   - DFAT Consolidated List",
             "   - EU sanctions list (Council Regulation 269/2014)",
             "   - OFAC SDN List (US)",
             "   - UK sanctions list",
             "   Result: NO MATCHES on any list.",
             "",
             "2. PEP SCREENING:",
             "   No beneficiary or officeholder identified as a Politically Exposed Person.",
             "",
             "3. TRANSACTION MONITORING:",
             "   Distributions for FY2024 reviewed. No suspicious patterns identified.",
             "   Distribution to Eastbridge Holdings Pte Ltd (Singapore) flagged for "
             "   review -- confirmed legitimate business purpose (consulting fees).",
             "",
             "4. CHANGE OF CIRCUMSTANCES:",
             "   Trustee changed from Pemberton Holdings Pty Ltd to Pemberton Advisory "
             "   Pty Ltd on 1 February 2024. Updated records accordingly.",
             "",
             "5. RECOMMENDATION:",
             "   Continue at MEDIUM-HIGH risk rating due to foreign elements.",
             "   Next review due: 15 March 2025.",
             "",
             "Sandra Chen",
             "Compliance Officer",
             "Henderson Chambers & Partners",
         ]),
    ]

    for title, lines in filler_sections:
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 14)
        pdf.cell(0, 10, title, align="C", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(5)
        pdf.set_font("Helvetica", "", 10)
        for line in lines:
            if line:
                pdf.multi_cell(0, 5.5, line)
            pdf.ln(2)

        if random.random() > 0.3:
            pdf.scan_artifact()

    # Keep adding pages until we hit target
    while pdf.page_no() < target_pages:
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 12)
        page_type = random.choice([
            "INTERNAL FILE NOTE",
            "COMPLIANCE REVIEW WORKSHEET",
            "RISK ASSESSMENT MATRIX",
            "DOCUMENT TRACKING REGISTER",
        ])
        pdf.cell(0, 10, page_type, align="C", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(5)
        pdf.set_font("Helvetica", "", 10)

        # Fill with realistic boilerplate
        for _ in range(random.randint(8, 15)):
            boilerplate = random.choice([
                "Review of Trust Deed and all Variation Deeds completed. No further "
                "amendments required at this time. Trust structure remains compliant "
                "with all applicable legislation.",
                "Annual distribution resolution reviewed and filed. All distributions "
                "made in accordance with the Trustee's powers under Clause 10 of the "
                "Original Deed.",
                "DFAT sanctions list checked against all current beneficiaries. No "
                "matches found. Next scheduled check: quarterly.",
                "Client file reviewed for completeness. All identity documents current. "
                "Passport expiry dates noted and diarised for follow-up.",
                "Foreign entity documentation reviewed. Singapore ACRA extract and "
                "Hong Kong Companies Registry extract obtained and filed.",
                "Trustee change documentation reviewed. All ASIC forms lodged. Property "
                "transfer documentation in progress.",
                "AML risk assessment reviewed. Risk rating remains MEDIUM-HIGH due to "
                "the presence of foreign corporate beneficiaries and a foreign national "
                "beneficiary.",
                "Compliance training records updated. All relevant staff completed "
                "AML/CTF awareness training within the last 12 months.",
                "Ongoing monitoring program reviewed. Transaction monitoring alerts "
                "reviewed and cleared. No suspicious matters identified.",
                "Client engagement letter reviewed. Terms of engagement remain current. "
                "Professional indemnity insurance coverage confirmed.",
            ])
            pdf.multi_cell(0, 5.5, boilerplate)
            pdf.ln(3)

        if random.random() > 0.5:
            pdf.handwritten_note(random.choice([
                "Reviewed and filed. No action required. -- SC",
                "Follow up with client re: updated passport copy. -- SC",
                "Check DFAT list update due next week. -- GH",
                "Marcus called -- confirmed no changes to beneficiaries. -- SC",
                "File note: Dorothy Pemberton now in aged care facility. "
                "Address updated in records. -- SC, 04/2024",
            ]))

        pdf.scan_artifact()


def generate_full_bundle(output_path: str, target_pages: int = 108):
    """Generates the complete compliance bundle."""
    pdf = TrustBundlePDF()
    pdf.set_auto_page_break(auto=True, margin=20)

    print("Generating sections...")

    print("  [1/8] Original Trust Deed (~25 pages)")
    add_original_deed(pdf)

    print("  [2/8] Variation Deed No. 1 -- Remove Rebecca, Add Vladimir Petrov")
    add_variation_deed_1(pdf)

    print("  [3/8] Variation Deed No. 2 -- Add Singapore & Hong Kong entities")
    add_variation_deed_2(pdf)

    print("  [4/8] Deed of Retirement & Appointment -- Change of Trustee")
    add_trustee_change(pdf)

    print("  [5/8] ASIC Company Extracts")
    add_asic_extracts(pdf)

    print("  [6/8] Trustee Meeting Minutes (FY2019-2024)")
    add_meeting_minutes(pdf)

    print("  [7/8] Solicitor Correspondence & ID Documents")
    add_solicitor_correspondence(pdf)
    add_id_documents(pdf)
    add_stamp_duty(pdf)

    print(f"  [8/8] Filler pages to reach {target_pages}+ pages")
    add_filler_pages(pdf, target_pages)

    pdf.output(output_path)
    size = os.path.getsize(output_path)
    pages = pdf.page_no()
    print(f"\nGenerated: {output_path}")
    print(f"File size: {size:,} bytes ({size/1024:.0f} KB)")
    print(f"Total pages: {pages}")

    # ---- Ground Truth for Pipeline Validation ----
    print("\n" + "=" * 60)
    print("GROUND TRUTH (for pipeline validation)")
    print("=" * 60)
    print(f"Trust Name:        The Pemberton Family Trust")
    print(f"ABN:               53 714 289 301")
    print(f"")
    print(f"CURRENT Trustee:   Pemberton Advisory Pty Ltd (ACN 672 831 059)")
    print(f"  [Changed from Pemberton Holdings Pty Ltd on 01/02/2024]")
    print(f"")
    print(f"CURRENT Beneficiaries (9 total):")
    print(f"  1. Marcus Edward Pemberton (Primary) -- Australian citizen")
    print(f"  2. Sarah Louise Pemberton -- Australian citizen")
    print(f"  3. Thomas James Pemberton -- Australian citizen")
    print(f"  4. Emily Grace Pemberton -- Australian citizen")
    print(f"  5. Dorothy May Pemberton -- Australian citizen")
    print(f"  6. Vladimir Ivanovich Petrov -- Russian citizen, AU PR")
    print(f"  7. Pemberton Capital Group Pty Ltd (Australian)")
    print(f"  8. Eastbridge Holdings Pte Ltd (Singapore)")
    print(f"  9. Pemberton-Chen International Limited (Hong Kong)")
    print(f"")
    print(f"EXCLUDED (Schedule 3):")
    print(f"  - Rebecca Anne Pemberton (removed via Variation 1, 22/03/2021)")
    print(f"")
    print(f"Is High Risk:      TRUE")
    print(f"  - Foreign national beneficiary (Russia)")
    print(f"  - Foreign corporate beneficiaries (Singapore, Hong Kong)")
    print(f"  - JV with non-family entity (Chen Family Holdings)")
    print(f"")
    print(f"Expected DFAT Matches:")
    print(f"  - 'Vladimir Ivanovich Petrov' vs 'Vladimir Ivanov' (mock DFAT)")
    print(f"    token_set_ratio should score ~85+ (partial name match)")


if __name__ == "__main__":
    output = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_pemberton_trust_bundle.pdf")
    generate_full_bundle(output)
