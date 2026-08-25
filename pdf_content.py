"""The whitepaper text. Run this to produce the PDF.

    python pdf_content.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from reportlab.platypus import PageBreak, Spacer  # noqa: E402

import build_pdf as G  # noqa: E402
import pdf_document as D  # noqa: E402
import sppi_brand as B  # noqa: E402
from build_pdf import FINDINGS, FOLLOWUPS, PLACEBO  # noqa: E402

ART = B.BRAND_DIR
OUT = G.OUT

ABOUT = [
    "The Southwest Public Policy Institute (SPPI) is a research institute and "
    "think tank dedicated to advancing data-driven solutions that promote "
    "economic freedom, public safety, educational opportunity, and personal "
    "responsibility.",
    "Unlike traditional think tanks that often preach to the choir, SPPI acts "
    "as a &ldquo;do-tank&rdquo;, rejecting the echo chamber. We engage diverse "
    "audiences by micro-targeting constituents on the issues that matter most, "
    "meeting people where they are, not where political ideologies expect them "
    "to be.",
    "Our approach is grounded in rigorous consumer emulation, replicating "
    "real-world experiences to test how policies, systems, and markets actually "
    "work for everyday Americans. From applying for credit and navigating "
    "public services to requesting public records and scrutinizing regulations, "
    "we investigate barriers that affect families and small businesses alike, "
    "offering tangible reforms grounded in lived experience.",
    "SPPI&rsquo;s work spans nationwide, with a unifying goal: to reinvigorate "
    "timeless American principles of liberty, accountability, and community. We "
    "believe that respectful dialogue, practical problem-solving, and open "
    "exchange&mdash;not division&mdash;are the keys to a freer and more "
    "prosperous future.",
    "We champion innovation at the national, regional, state, and local levels "
    "by empowering individuals, encouraging entrepreneurship, and expanding the "
    "role of voluntary, community-driven solutions. With one guiding "
    "principle&mdash;WE AGREE&mdash;we seek to restore trust in the policymaking "
    "process and deliver what public service should always provide: better "
    "living through better policy.",
]


def story():
    P, H, SH = D.P, D.H, D.SH
    cov = FINDINGS["coverage"]
    tp = FINDINGS["templating"]
    pct = 100 * tp["complaints_in_templates"] / tp["narratives_scored"]
    dow = FOLLOWUPS["day_of_week"]
    gs = FOLLOWUPS["geo_split_stats"]
    rel = FOLLOWUPS["relief"]
    cr24, dc24 = rel["credit_reporting_2024"], rel["debt_collection_2024"]
    life = FOLLOWUPS["template_lifespan"]
    long_lived = sum(r["complaints"] for r in life
                     if r["band"] in ("1-2 years", "over 2 years"))
    s = []

    # ---- about page ----
    s.append(H("Southwest Public Policy Institute"))
    for para in ABOUT:
        s.append(P(para))
    s.append(PageBreak())

    # ---- executive summary ----
    s.append(H("Executive Summary"))
    s.append(P(
        f"This paper examines every consumer complaint in six product segments "
        f"of the Consumer Financial Protection Bureau&rsquo;s public complaint "
        f"database &mdash; {cov['n']:,} complaints received between "
        f"December 2011 and 19 August 2026, matching the "
        f"Bureau&rsquo;s own published count for that scope exactly. It is a "
        f"census, not a sample.", "first"))
    s.append(P(
        "It was undertaken to test two claims. The first is that complaints are "
        "being filed at industrial scale from templates rather than written by "
        "the consumers whose names appear on them. The second is that the "
        "extraordinary growth in complaint volume followed the public&rsquo;s "
        "adoption of large language models, which would make artificial "
        "intelligence a driver of regulatory workload."))
    s.append(P(
        f"The first claim is substantiated. Of {tp['narratives_scored']:,} "
        f"published narratives long enough to compare, "
        f"<b>{tp['complaints_in_templates']:,} &mdash; {pct:.1f} percent &mdash; "
        f"are byte-identical to at least forty-nine others</b>, reusing "
        f"{tp['template_texts']:,} distinct texts that each appear fifty times "
        f"or more. The most-copied single text has been filed 30,896 times "
        f"against thirteen firms in fifty-two jurisdictions."))
    s.append(P(
        "The second claim is not supported. Every large language model "
        "milestone produces a statistically significant regression coefficient, "
        "and every one of them fails a placebo test. Templating rises "
        "continuously from 2019 and shows no break at any milestone. The "
        "estimated effect even changes sign between segments, which is the "
        "signature of a model describing ordinary growth rather than an event."))

    s.append(SH("Six findings frame this brief"))
    s.append(D.bullets([
        f"<b>A quarter of published complaint narratives are literal copies.</b> "
        f"{tp['complaints_in_templates']:,} complaints reuse a text that appears "
        f"at least fifty times. In credit reporting the share reaches 44 percent "
        f"by mid-2025.",

        "<b>The templates are recitations of statute, not accounts of harm.</b> "
        "The largest reproduces the preamble of the Fair Credit Reporting Act "
        "and a list of account numbers. Others invoke &ldquo;estoppel by "
        "silence&rdquo; or demand blocks under the identity-theft provision.",

        "<b>Templating is confined to credit reporting and debt collection.</b> "
        "It runs at 44 and 24 percent in those two segments and at approximately "
        "zero in mortgages, cards, student loans and consumer loans. A "
        "general-purpose writing tool would not select two segments; an industry "
        "that operates in credit disputes would.",

        f"<b>The filings keep office hours.</b> Templated complaints arrive at "
        f"weekends {dow['templated_weekend_pct']:.1f} percent of the time against "
        f"{dow['organic_weekend_pct']:.1f} percent for the rest &mdash; roughly half "
        f"as often. {long_lived:,} templated complaints come from templates in "
        f"continuous use for more than a year.",

        f"<b>Templated disputes obtain relief more often than organic ones.</b> "
        f"{cr24['templated']['relief_pct']:.1f} percent against "
        f"{cr24['organic']['relief_pct']:.1f} percent in credit reporting, and "
        f"{dc24['templated']['relief_pct']:.1f} against "
        f"{dc24['organic']['relief_pct']:.1f} percent in debt collection. Almost "
        f"none of it is monetary; nearly all of it is deletion or correction of "
        f"a tradeline.",

        "<b>Artificial intelligence did not cause this.</b> The practice was "
        "operating at scale years before ChatGPT was released, and no complaint "
        "series shows a structural break at any model release date.",
    ], numbered=True))

    s.append(SH("Recommendation"))
    s.append(P(
        "The Bureau should publish a provenance field. The complaint form "
        "already asks whether a third party is submitting on the "
        "consumer&rsquo;s behalf; that answer is not in the public file. "
        "Publishing it, together with a submission-method breakdown finer than "
        "the present six categories, would let the public distinguish an "
        "individual grievance from a brokered filing without any new burden on "
        "consumers. Every conclusion in this paper that concerns provenance is "
        "an inference drawn because that one field is withheld."))

    # ---- data ----
    s.append(H("Data"))
    s.append(P(
        "The Bureau publishes complaints through a search interface with a "
        "documented export. The extract underlying this paper was taken on "
        "20 August 2026 by date-windowed export against that interface, with no "
        "key or special access, and stored locally. Reproduction instructions "
        "appear in the notes.", "first"))
    s.append(D.table(
        ["Segment", "Complaints", "First", "Last"],
        [[r["segment"].replace("_", " ").title(), f"{r['n']:,}",
          r["first_date"], r["last_date"]] for r in FINDINGS["segments"]],
        [150, 100, 73, 73], align_right=(1,)))
    s.append(P(
        f"Of these, {cov['narratives']:,} carry a narrative the consumer "
        f"consented to publish, about 21 percent. Narratives are the only "
        f"window the public file offers onto who wrote a complaint, so every "
        f"text-based finding below describes that consenting subset."))
    s.append(D.figure(ART / "fig_volume.png",
        "Figure 1. Monthly complaint volume, log scale. Credit reporting "
        "accounts for 14.0 million of the 16.5 million complaints examined, "
        "rising from roughly one hundred a month in 2012 to more than six "
        "hundred thousand by mid-2026."))

    # ---- templates ----
    s.append(H("Templates"))
    s.append(P(
        f"After normalising case, punctuation and the Bureau&rsquo;s redaction "
        f"markers, {tp['complaints_in_templates']:,} of "
        f"{tp['narratives_scored']:,} narratives are byte-identical to at least "
        f"forty-nine others. These are exact duplicates, not paraphrases. That "
        f"distinction matters for defensibility, and it is the reason every "
        f"headline figure in this paper uses exact matching.", "first"))
    from build_report import top_templates
    tops = top_templates(5)
    s.append(D.table(
        ["Copies", "Firms", "Jurisdictions", "Active", "Opening words"],
        [[f"{t['size']:,}", t["companies"], t["states"],
          f"{t['first']} to {t['last']}",
          (t["text"][:96] + "&hellip;")] for t in tops],
        [46, 34, 62, 76, 178], align_right=(0, 1, 2)))
    s.append(P(
        "Jurisdiction counts exceed fifty because the Bureau&rsquo;s state "
        "field also carries the District of Columbia, Puerto Rico, the "
        "territories and the military codes AA, AE and AP.", "caption"))
    s.append(P(
        "The largest group recites the statute rather than describing anything "
        "that happened to the filer:"))
    s.append(P(
        "&ldquo;In accordance with the Fair Credit Reporting act. The List of "
        "accounts below has violated my federally protected consumer rights to "
        "privacy and confidentiality under 15 USC 1681. [account list] 15 U.S.C "
        "1681 section 602 A. States I have the right to privacy&hellip;&rdquo;",
        "quote"))
    s.append(P(
        "A second family, filed identically 14,558 times against three firms in "
        "forty-one jurisdictions, answers a question the form asks:"))
    s.append(P(
        "&ldquo;I&rsquo;m really not sure what happened. I have mailed off "
        "letters to the credit bureaus continuously and thus far I have not "
        "gotten a response. My name is XXXX XXXX and I am filing this complaint "
        "for falsely reporting misleading information. <b>There is no third "
        "party involved.</b> PLease review the uploaded letters.&rdquo;",
        "quote"))
    s.append(P(
        "This should be weighed carefully rather than treated as a confession. "
        "A consumer who copied a free script and filed it personally is telling "
        "the truth: no third party submitted for them. What the passage "
        "establishes is that whoever wrote the template anticipated the "
        "Bureau&rsquo;s question and supplied an answer to it."))

    s.append(SH("Templating is confined to two segments"))
    by = FINDINGS["templated_share_by_month"]
    rows = []
    for seg in ["credit_reporting", "debt_collection", "card", "consumer_loan",
                "student_loan", "mortgage"]:
        r = by.get(seg, {}).get("2025-07")
        rows.append([seg.replace("_", " ").title(),
                     f"{r['pct']:.1f}%" if r else "&mdash;"])
    s.append(D.table(["Segment", "Templated share of narratives, July 2025"],
                     rows, [180, 216], align_right=(1,)))
    s.append(P(
        "This specificity is the strongest single argument against the "
        "artificial-intelligence explanation. If consumers were drafting "
        "complaints with chatbots, templated text would appear wherever "
        "consumers complain. Instead it appears in the two segments where the "
        "credit-repair industry operates and essentially nowhere else."))

    # ---- provenance ----
    s.append(H("Provenance"))
    s.append(P(
        "Identical text cannot by itself distinguish a paid operation filing "
        "for a client book from a free script that spread on social media. The "
        "distinction governs the remedy, because the Credit Repair "
        "Organizations Act reaches paid organizations and nothing else. Two "
        "properties of the filings speak to it without identifying anyone.",
        "first"))
    s.append(SH("Lifespan"))
    s.append(D.table(
        ["Template active for", "Templates", "Complaints"],
        [[r["band"], f"{r['templates']:,}", f"{r['complaints']:,}"]
         for r in life], [180, 108, 108], align_right=(1, 2)))
    s.append(P(
        f"A script that goes viral burns out. A business runs for years. "
        f"{long_lived:,} templated complaints &mdash; the majority &mdash; come "
        f"from templates in continuous use for over a year, and 238 templates "
        f"have been running for more than two. The median template in every "
        f"band is filed against exactly three firms, which are the three "
        f"national credit bureaus."))
    s.append(SH("Day of week"))
    s.append(D.table(
        ["Day received", "Templated", "Organic"],
        [[d, f"{dow['templated'][d]:.1f}%", f"{dow['organic'][d]:.1f}%"]
         for d in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]],
        [180, 108, 108], align_right=(1, 2)))
    s.append(P(
        f"Templated credit-reporting complaints arrive at weekends "
        f"{dow['templated_weekend_pct']:.1f} percent of the time; the rest arrive "
        f"at weekends {dow['organic_weekend_pct']:.1f} percent of the time. People "
        f"filing their own grievances do it on Saturday. Templated filings keep "
        f"office hours. Across {dow['n_templated']:,} templated and "
        f"{dow['n_organic']:,} organic narratives, this is the clearest "
        f"provenance signal available that requires no reading of the text."))
    s.append(SH("Three bureaus moving together"))
    s.append(P(
        "Through 2024, credit-reporting volume rose from 101,735 to 267,923 "
        "complaints a month. Broken out by respondent, TransUnion rose 2.27 "
        "times, Experian 2.43 times and Equifax 2.25 times over the same twelve "
        "months. Consumers filing individually, using whatever template they "
        "happened to encounter, would not produce near-identical multipliers "
        "against three independent companies. Software submitting the same "
        "dispute to all three at once would."))

    # ---- geography ----
    s.append(H("Geography"))
    s.append(P(
        "Filing rates differ across states by more than an order of magnitude. "
        "Georgia filed 3,430 credit-reporting complaints per hundred thousand "
        "residents in 2025; Wyoming filed 131. The high-rate states form a "
        "contiguous Deep South and Gulf cluster.", "first"))
    s.append(P(
        "It is tempting to read this as a map of coordinated filing, and an "
        "earlier draft of this analysis did. That reading does not survive "
        "scrutiny. Templated complaints sit inside the numerator of the filing "
        "rate, so a heavily templated state is mechanically a high-rate state. "
        "Rating templated and organic narratives separately removes the "
        "circularity."))
    gr = FOLLOWUPS["geo_split"]
    rows = []
    for r in gr[:5] + gr[-4:]:
        ratio = r["templated_per_100k"] / max(r["organic_per_100k"], 0.01)
        rows.append([r["state"], f"{r['templated_per_100k']:,.0f}",
                     f"{r['organic_per_100k']:,.0f}", f"{ratio:.2f}"])
    s.append(D.table(
        ["State", "Templated per 100k", "Organic per 100k", "Ratio"],
        rows, [72, 120, 120, 84], align_right=(1, 2, 3)))
    s.append(P(
        f"Separated, the two rates correlate at "
        f"{gs['correlation_templated_vs_organic']}. Organic narrative filing on "
        f"its own varies {gs['organic_max_min_ratio']}-fold across states; "
        f"templated filing varies {gs['templated_max_min_ratio']}-fold. States "
        f"that file a great deal file a great deal of both kinds. Georgia, the "
        f"highest-rate state in the country, is actually under-templated "
        f"relative to its organic volume."))
    s.append(P(
        "The straightforward rival explanation &mdash; that Alabama, "
        "Mississippi and Louisiana have among the weakest credit-score "
        "distributions in the country and therefore the most genuine disputes "
        "to bring &mdash; predicts exactly this pattern. What survives is "
        "narrower than the headline correlation suggested: a modest templating "
        "excess in a few Gulf states, not a geographic fingerprint of "
        "coordination."))

    # ---- outcomes ----
    s.append(H("Outcomes"))
    s.append(P(
        "Whether any of this works for the consumer is answerable from the "
        "file. The Bureau records how each complaint closed.", "first"))
    s.append(D.figure(ART / "fig_relief.png",
        "Figure 2. Share of closed complaints resolved with relief, templated "
        "against organic filings."))
    s.append(P(
        f"Templated credit-reporting complaints obtained relief "
        f"{cr24['templated']['relief_pct']:.1f} percent of the time against "
        f"{cr24['organic']['relief_pct']:.1f} percent for the rest. In debt "
        f"collection the gap is far wider. Monetary relief is negligible in "
        f"every category, well under a tenth of one percent, so essentially all "
        f"of this is non-monetary relief &mdash; in credit reporting, the "
        f"deletion or correction of a tradeline."))
    s.append(P(
        "Two readings are available and the public data cannot separate them. "
        "The first is that mass templated disputes succeed precisely because a "
        "bureau facing industrial dispute volume cannot verify each item inside "
        "the statutory window, so contested entries are deleted whether or not "
        "they were wrong. That is the credit-washing concern, and it would "
        "explain why the practice sustains templates for years. The second is "
        "that the disputes are largely meritorious. The file records that an "
        "item was removed, never whether removing it was correct."))
    s.append(P(
        "What the result does rule out is the tidiest consumer-protection "
        "story. These filings are not consumers paying for something that does "
        "nothing. Whatever else is true, the templated dispute is the more "
        "effective instrument."))
    s.append(P(
        "One complaint against a credit-repair firm, filed in December 2024, "
        "states the customer&rsquo;s side of that bargain directly:"))
    s.append(P(
        "&ldquo;I started doing business with Lexington Law a few months ago. "
        "The company is charging me for services that they are not providing. "
        "My [score] is going down, and they are disputing positive items "
        "causing my credit report score to decrease.&rdquo;", "quote"))

    # ---- language models ----
    s.append(H("Language Models"))
    s.append(P(
        "An interrupted time-series regression was fitted at three milestones "
        "&mdash; the public launch of ChatGPT on 30 November 2022, its "
        "mass-adoption point at the end of January 2023, and the release of "
        "GPT-4 on 14 March 2023 &mdash; on monthly complaint counts, using a "
        "negative binomial model because the counts are heavily overdispersed.",
        "first"))
    s.append(P(
        "Taken at face value, the high-volume series appear to confirm the "
        "hypothesis. Credit reporting shows a level shift of 21.8 percent at "
        "the ChatGPT launch with a p-value of 0.010; the combined series shows "
        "36.1 percent at below 0.001. Reported alone, these would read as a "
        "finding."))
    s.append(P(
        "They are an artefact. The complaint series grows steeply and "
        "non-linearly across its entire life, long before any such model "
        "existed, and a segmented regression fitted to a curve of that shape "
        "returns a large significant break at almost any date, because the "
        "break term absorbs ordinary curvature."))
    s.append(D.figure(ART / "fig_placebo.png",
        "Figure 3. Placebo distribution for credit reporting. Each bar counts "
        "dates at which nothing relevant happened, by the size of the effect "
        "the model reports there. The estimate at the ChatGPT launch sits at "
        "the 28th percentile: 93 of 129 irrelevant dates produce a larger "
        "effect."))
    s.append(D.table(
        ["Segment", "Level change", "p", "Placebo percentile"],
        [["Credit reporting", "+21.8%", "0.010", "28th"],
         ["Debt collection", "&minus;22.1%", "0.00003", "3rd"],
         ["Mortgage", "&minus;6.5%", "0.285", "27th"],
         ["Cards", "+34.8%", "&lt;0.001", "82nd"],
         ["Student loans", "&minus;2.1%", "0.922", "2nd"],
         ["Consumer loans", "&minus;5.3%", "0.565", "7th"],
         ["All six combined", "+36.1%", "&lt;0.001", "26th"]],
        [150, 90, 78, 78], align_right=(1, 2, 3)))
    s.append(P(
        "No segment clears its placebo distribution. More tellingly, the sign "
        "of the effect flips: positive 34.8 percent for cards, negative 22.1 "
        "percent for debt collection, negative 6.5 percent for mortgages. A "
        "technology that made complaints easier to write would push every "
        "consumer-facing segment in the same direction."))
    s.append(P(
        "Cards is the one segment where the placebo test does not dismiss the "
        "milestones, sitting at the 82nd percentile. Two things argue against "
        "reading even that as an effect. The segment&rsquo;s own detected "
        "break falls in October 2022, some sixty days <i>before</i> the "
        "ChatGPT launch, and a break cannot be caused by an event that has not "
        "happened. And card narratives are 1.3 percent templated, so whatever "
        "drove the volume was not producing duplicated text."))
    s.append(D.figure(ART / "fig_templating.png",
        "Figure 4. Share of narratives byte-identical to at least forty-nine "
        "others. Credit reporting climbs from under one percent in 2016 "
        "through eighteen percent by October 2022, before ChatGPT, to about "
        "fifty percent by late 2025. The trend runs straight through the "
        "launch line."))
    s.append(P(
        "This is the clearest refutation. Had these models driven templated "
        "filing, the curve would inflect at the launch. It does not. It begins "
        "rising in 2019 and continues on the same trajectory. Note also that "
        "model assistance would <i>reduce</i> exact duplication, since a "
        "chatbot paraphrases rather than copies. That nearly half of 2025 "
        "narratives are literal copies indicates bulk filing remains "
        "copy-and-paste."))

    # ---- method ----
    s.append(H("Method"))
    s.append(P(
        "Four controls did real work, in the sense that omitting any one of "
        "them would have changed a conclusion.", "first"))
    s.append(SH("The Bureau renamed its product categories inside the window"))
    s.append(P(
        "Credit reporting exists under three different product labels. The "
        "current one, holding 11.7 million complaints, begins on 24 August "
        "2023 &mdash; nine months after the ChatGPT launch. Grouped on the raw "
        "field, a series of 2.2 million collapses to zero while one of 11.7 "
        "million appears from nothing, inside the very window under test. All "
        "series here are grouped on a canonical crosswalk instead. The renames "
        "are demonstrably administrative: credit reporting, cards and consumer "
        "loans all change label on the same two dates."))
    s.append(SH("Placebo distributions rather than p-values"))
    s.append(P(
        "Every intervention estimate is refitted at every other candidate date "
        "in the series. Without this test, seven significant coefficients would "
        "have been reported as findings and none survives it."))
    s.append(SH("Redaction inflates apparent similarity"))
    s.append(P(
        "The Bureau replaces names, dates and addresses with runs of X, so "
        "unrelated complaints share tokens through scrubbing alone. Redaction "
        "runs are collapsed and discarded before comparison."))
    s.append(SH("Near-duplicate clusters chain"))
    s.append(P(
        "Clustering at a similarity threshold links 2.03 million narratives, "
        "but that figure is not template membership: clusters are connected "
        "components under single linkage, so one document joins another "
        "whenever some third resembles both. The largest component contains "
        "pairs as dissimilar as 0.36 against a 0.80 threshold. Filtered to "
        "clusters whose members genuinely meet the threshold, 5,098 clusters "
        "cover 693,947 complaints. Exact duplication, where chaining cannot "
        "occur, is used for every headline number instead."))

    # ---- limits ----
    s.append(H("Limits"))
    s.append(D.bullets([
        "<b>This is not a finding that the underlying disputes are false.</b> "
        "A templated complaint can describe a real error. Templating is "
        "evidence about who drafted and filed a document, not about the merits "
        "of the grievance.",
        "<b>No firm is identified as a filer.</b> The company field names the "
        "respondent. Complaint spikes for credit-repair firms in this data are "
        "complaints <i>against</i> those firms, from their own customers.",
        "<b>This is not a finding that language models play no role.</b> Exact "
        "matching is blind to paraphrase, and model-assisted drafting would "
        "show up as a decline in exact duplication. The finding is that model "
        "adoption does not explain the volume or templating trends.",
        "<b>Narratives are a consenting subset.</b> About 21 percent of "
        "complaints carry one, and consent is unlikely to be random with "
        "respect to whether a template was used.",
        "<b>Credit-reporting narrative publication collapsed in 2026,</b> from "
        "about 25 percent to between 0.1 and 3 percent from January onward, "
        "while mortgage held between 28 and 46 percent across the same months. "
        "A processing backlog does not select one segment and spare another. "
        "Text analysis has no coverage of 2026, and that period is excluded "
        "from every text-based figure here. Filing itself continued normally, "
        "at twenty-four to twenty-nine thousand complaints on weekdays through "
        "mid-August.",
    ]))

    # ---- recommendations ----
    s.append(H("Recommendations"))
    s.append(D.bullets([
        "<b>Publish the third-party field.</b> The complaint form already asks "
        "whether someone is submitting on the consumer&rsquo;s behalf. "
        "Publishing that answer would settle in one column what this paper has "
        "to infer from lifespan, filing hours and respondent lockstep.",
        "<b>Report dispute outcomes by provenance.</b> If templated disputes "
        "obtain deletion at materially higher rates than individually written "
        "ones, that is a supervisory fact about the accuracy of the "
        "reinvestigation process, and it is measurable today.",
        "<b>Explain the 2026 narrative gap.</b> A seven-month, "
        "segment-specific collapse in narrative publication should be "
        "documented, whether it is a backlog or a policy change.",
        "<b>Do not read complaint volume as a measure of consumer harm.</b> "
        "Volume in the largest segment is substantially a function of filing "
        "technology and industry activity. Any policy or enforcement metric "
        "keyed to raw complaint counts is measuring the dispute industry as "
        "much as the conduct of the firms complained about.",
    ]))

    # ---- conclusion ----
    s.append(H("Conclusion"))
    s.append(P(
        "The federal consumer complaint database is often treated as a "
        "barometer of how financial firms treat Americans. In its largest "
        "segment it has become something else: a channel through which a "
        "dispute industry submits standardised documents at volume, with "
        "measurable success at getting entries removed from credit files.",
        "first"))
    s.append(P(
        "That finding cuts across the usual alignments. It is not an argument "
        "that consumers are lying, and the data cannot support such an "
        "argument. Many of the disputes are doubtless meritorious, and the "
        "relief rates are consistent with that. But a database in which a "
        "quarter of published narratives are literal copies of one another "
        "cannot be read as a straightforward record of individual experience, "
        "and decisions that rest on counting complaints should account for "
        "that."))
    s.append(P(
        "The artificial-intelligence hypothesis, which prompted this "
        "examination, is not supported. The practice predates the technology "
        "by several years and is concentrated in exactly the two segments "
        "where a commercial dispute industry operates. The more mundane "
        "explanation fits the evidence better, and it is the one for which "
        "Congress has already written a statute."))

    # ---- notes ----
    s.append(H("Notes"))
    notes = [
        "Extract taken 20 August 2026 from the CFPB Consumer Complaint "
        "Database public search API, covering complaints received 1 December "
        "2011 to 19 August 2026 in six canonical product segments. "
        "16,533,564 complaints, matching the API&rsquo;s reported total for "
        "that scope exactly.",
        "Segments are canonical groupings of the Bureau&rsquo;s raw product "
        "labels, which have been renamed twice. The crosswalk is documented in "
        "the analysis code.",
        "Templating is measured as exact duplication after normalising case, "
        "punctuation and redaction markers, restricted to narratives of at "
        "least twenty-five words, with a template defined as a text appearing "
        "fifty or more times.",
        "Interrupted time-series estimates use a negative binomial model with "
        "monthly seasonality; placebo distributions refit the same "
        "specification at every candidate date at least twelve months from "
        "either end of the series and more than six months from the real date.",
        "Per-capita rates use Census Bureau state population estimates for the "
        "year in which each complaint was received. Territories and military "
        "postal codes have no state denominator and are excluded.",
        "Relief rates use the company_response field, excluding complaints not "
        "yet closed. &ldquo;Relief&rdquo; combines monetary and non-monetary "
        "relief.",
        "Analysis code, the canonical crosswalk, the registry of competing "
        "events with citations, and instructions to reproduce the extract are "
        "held with this paper at the Southwest Public Policy Institute.",
    ]
    for i, n in enumerate(notes, 1):
        s.append(D.P(f"{i}&nbsp;&nbsp;{n}", "note"))
    return s


def main():
    real = B.register_fonts()
    global_styles = B.styles()
    D.S = global_styles
    print("Minion Pro embedded:", real)

    ART.mkdir(exist_ok=True)
    print("rendering cover art...")
    art = G.make_cover_art(ART / "cover_art.png")
    print("rendering figures...")
    G.chart_volume(ART / "fig_volume.png")
    G.chart_templating(ART / "fig_templating.png")
    G.chart_placebo(ART / "fig_placebo.png")
    G.chart_relief(ART / "fig_relief.png")

    print("drawing cover...")
    cover = D.draw_cover(D.TMP / "_cover.pdf", art)

    print("building body...")
    body = D.TMP / "_body.pdf"
    doc = D.Doc(body)
    doc.build(story())

    from pypdf import PdfReader, PdfWriter
    w = PdfWriter()
    for p in PdfReader(str(cover)).pages:
        w.add_page(p)
    for p in PdfReader(str(body)).pages:
        w.add_page(p)
    w.add_metadata({
        "/Title": f"{G.TITLE}: {G.SUBTITLE}",
        "/Author": G.AUTHORS,
        "/Subject": "Analysis of 16.5 million CFPB consumer complaints",
        "/Creator": "Southwest Public Policy Institute",
    })
    with open(D.PDF_PATH, "wb") as fh:
        w.write(fh)
    print(f"wrote {D.PDF_PATH}  ({D.PDF_PATH.stat().st_size/1e6:.1f} MB, "
          f"{len(PdfReader(str(D.PDF_PATH)).pages)} pages)")


if __name__ == "__main__":
    main()
