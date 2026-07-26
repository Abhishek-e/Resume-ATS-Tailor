"""
Company placement-prep dashboard.

Layout and feature set are modelled on the "all companies dashboard" pattern
that placement-prep sites use - a grid of company cards, each opening a set of
practice questions gated behind an account. The *content* here is written from
scratch: company facts (sector, typical interview rounds) are public
information, and every question below is original. Nothing is copied from
another site, so nothing here carries someone else's licence.

Counts shown in the UI are derived from this data, never hard-coded, so the
dashboard cannot advertise more practice material than it actually has.
"""
from typing import Optional

# How much of a set a signed-out visitor gets to read. The rest is withheld
# server-side - the blur in the browser is presentation, not the access check.
GUEST_PREVIEW_QUESTIONS = 1

# `rounds` follows the order a candidate meets them. `focus` drives the search
# box. Difficulty is a coarse three-step scale used for the card badge.
COMPANIES = [
    {
        "slug": "tcs",
        "name": "TCS",
        "sector": "IT Services",
        "difficulty": "Moderate",
        "focus": ["Aptitude", "Coding", "Verbal"],
        "rounds": ["Online assessment", "Coding round", "Technical interview", "HR interview"],
        "blurb": "Volume hirer with a heavily weighted online assessment; clearing the "
                 "aptitude cut-off matters more here than deep system design.",
        "questions": [
            {"type": "Aptitude", "prompt": "A train covers 240 km at a steady speed. Had it "
             "moved 20 km/h faster the trip would have taken one hour less. Find the speed.",
             "answer": "60 km/h. Solve 240/v - 240/(v+20) = 1, giving v² + 20v - 4800 = 0."},
            {"type": "Coding", "prompt": "Given a string, return the length of the longest "
             "substring with no repeating characters. Aim for a single pass.",
             "answer": "Sliding window with a last-seen map; move the left edge to "
                       "last_seen[c] + 1 on a repeat. O(n) time, O(k) space."},
            {"type": "Technical", "prompt": "Explain the difference between a clustered and a "
             "non-clustered index, and when adding one can slow a system down.",
             "answer": "A clustered index defines physical row order (one per table); a "
                       "non-clustered index is a separate structure with pointers. Both add "
                       "write cost, so an index on a write-heavy, rarely-filtered column is a net loss."},
            {"type": "Verbal", "prompt": "Identify the error: 'Neither the manager nor the "
             "engineers was aware of the outage.'",
             "answer": "With 'neither/nor' the verb agrees with the nearer subject - "
                       "'engineers' - so it should read 'were aware'."},
            {"type": "HR", "prompt": "You are three days from a deadline and realise the "
             "approach you argued for is the wrong one. What do you do?",
             "answer": "Surface it immediately with a costed alternative. Interviewers are "
                       "testing whether you protect the project or your original position."},
        ],
    },
    {
        "slug": "infosys",
        "name": "Infosys",
        "sector": "IT Services",
        "difficulty": "Moderate",
        "focus": ["Aptitude", "Puzzles", "Coding"],
        "rounds": ["Online test", "Technical interview", "HR interview"],
        "blurb": "Puzzle-heavy reasoning section alongside standard quantitative aptitude; "
                 "the technical round stays close to what is on your CV.",
        "questions": [
            {"type": "Puzzle", "prompt": "Eight identical-looking coins include one that is "
             "lighter. Using a balance scale, find it in two weighings.",
             "answer": "Weigh 3 v 3. If balanced the fake is in the held-back pair - weigh "
                       "those. If not, take the lighter triple and weigh 1 v 1."},
            {"type": "Aptitude", "prompt": "Two pipes fill a tank in 12 and 18 minutes. A drain "
             "empties it in 36. All three open together - how long to fill?",
             "answer": "9 minutes. Rates 1/12 + 1/18 - 1/36 = 1/9 of the tank per minute."},
            {"type": "Coding", "prompt": "Rotate an n x n matrix 90 degrees clockwise in place.",
             "answer": "Transpose across the main diagonal, then reverse each row. No extra "
                       "matrix needed."},
            {"type": "Technical", "prompt": "What is a deadlock, and which of its four "
             "conditions is usually the cheapest one to break in practice?",
             "answer": "Mutual exclusion, hold-and-wait, no preemption, circular wait. Circular "
                       "wait is cheapest to break - impose a global lock ordering."},
            {"type": "HR", "prompt": "Why apply to a services company rather than a product one?",
             "answer": "Answer with something specific - client breadth, domain rotation, "
                       "structured training. A vague answer reads as an application sent everywhere."},
        ],
    },
    {
        "slug": "accenture",
        "name": "Accenture",
        "sector": "Consulting",
        "difficulty": "Moderate",
        "focus": ["Aptitude", "Communication", "SQL"],
        "rounds": ["Cognitive assessment", "Technical assessment", "Communication test", "HR interview"],
        "blurb": "The spoken-communication assessment is a real filter here, not a formality; "
                 "the technical half leans on SQL and fundamentals over algorithms.",
        "questions": [
            {"type": "SQL", "prompt": "Write a query returning the second-highest salary per "
             "department, handling departments where everyone earns the same.",
             "answer": "DENSE_RANK() OVER (PARTITION BY dept ORDER BY salary DESC) and filter "
                       "rank = 2. Ties collapse, so a single-salary department returns no row - "
                       "which is the correct result."},
            {"type": "Aptitude", "prompt": "A shopkeeper marks goods 40% above cost, then gives "
             "a 25% discount. What is the profit percentage?",
             "answer": "5%. Cost 100 -> marked 140 -> sold at 105."},
            {"type": "Technical", "prompt": "What does an API being idempotent mean, and which "
             "HTTP methods should be?",
             "answer": "Repeating the call leaves the same server state. GET, PUT and DELETE "
                       "should be idempotent; POST is not expected to be."},
            {"type": "Communication", "prompt": "Explain database normalisation to a client with "
             "no technical background, in under a minute.",
             "answer": "Use a concrete cost: storing a customer's address once instead of on "
                       "every order means one update, not hundreds, and no contradictions."},
            {"type": "HR", "prompt": "Describe a time you disagreed with a teammate's approach.",
             "answer": "Structure it - situation, your reasoning, how it resolved, what you "
                       "would repeat. Land on the outcome, not on being right."},
        ],
    },
    {
        "slug": "amazon",
        "name": "Amazon",
        "sector": "Product",
        "difficulty": "Hard",
        "focus": ["Data structures", "System design", "Leadership principles"],
        "rounds": ["Online assessment", "Technical phone screen", "On-site loop", "Bar raiser"],
        "blurb": "Behavioural answers are scored as rigorously as the code. Expect every "
                 "interviewer to map your stories onto the published leadership principles.",
        "questions": [
            {"type": "Coding", "prompt": "Given an array of integers and a target, return the "
             "indices of two numbers summing to it, in one pass.",
             "answer": "Walk the array keeping value -> index in a hash map; at each element "
                       "check whether target - value is already stored."},
            {"type": "Coding", "prompt": "Find the k most frequent elements in an array. Discuss "
             "why a full sort is the wrong choice.",
             "answer": "Count, then a size-k min-heap: O(n log k) versus O(n log n). Bucket "
                       "sort by frequency gets it to O(n)."},
            {"type": "System design", "prompt": "Design a URL shortener. Cover key generation, "
             "storage and the read path.",
             "answer": "Base62 of a counter or hash with collision retry; KV store keyed by "
                       "short code; cache aggressively - reads dominate writes by orders of magnitude."},
            {"type": "Behavioural", "prompt": "Tell me about a time you took on something well "
             "outside your assigned scope.",
             "answer": "Use STAR and quantify the result. State plainly what was yours versus "
                       "the team's - inflated ownership is what the bar raiser probes."},
            {"type": "Technical", "prompt": "What is eventual consistency, and name a feature "
             "where it is unacceptable.",
             "answer": "Replicas converge over time. Unacceptable for anything read-then-write "
                       "critical - inventory decrement on the last unit, or a payment balance check."},
        ],
    },
    {
        "slug": "microsoft",
        "name": "Microsoft",
        "sector": "Product",
        "difficulty": "Hard",
        "focus": ["Problem solving", "OOP design", "Debugging"],
        "rounds": ["Online assessment", "Technical rounds", "As-appropriate round"],
        "blurb": "Interviewers push on how you reason aloud and handle a changed requirement "
                 "mid-question, rather than on whether you recall a specific algorithm.",
        "questions": [
            {"type": "Coding", "prompt": "Detect whether a linked list has a cycle, and return "
             "the node where it begins, using O(1) extra space.",
             "answer": "Floyd's tortoise and hare. On meeting, reset one pointer to the head "
                       "and advance both one step at a time; they meet at the cycle start."},
            {"type": "Design", "prompt": "Model a parking lot with several vehicle sizes. What "
             "goes in the interface and what goes in the implementation?",
             "answer": "Interface: allocation and release. Implementation: per-size free lists "
                       "and pricing. Keep the fee rules out of the spot classes."},
            {"type": "Debugging", "prompt": "A service works locally but times out in production "
             "roughly one request in twenty. How do you narrow it down?",
             "answer": "Compare the environments first - data volume, connection pool size, "
                       "network hops. Intermittent-at-a-fixed-rate points at pool exhaustion "
                       "or one slow replica, not at the application logic."},
            {"type": "Technical", "prompt": "When would you choose composition over inheritance?",
             "answer": "Almost always - inheritance couples you to a base class's future. Reach "
                       "for it only on a genuine, stable 'is-a' with substitutability."},
            {"type": "Behavioural", "prompt": "Describe feedback that was hard to hear and what "
             "you changed because of it.",
             "answer": "Name the change concretely. An answer with no behaviour change reads "
                       "as deflection."},
        ],
    },
    {
        "slug": "deloitte",
        "name": "Deloitte",
        "sector": "Consulting",
        "difficulty": "Moderate",
        "focus": ["Case study", "Aptitude", "Business sense"],
        "rounds": ["Online assessment", "Group discussion", "Case interview", "HR interview"],
        "blurb": "The case interview rewards a stated structure before any number-crunching; "
                 "candidates lose it by jumping to an answer.",
        "questions": [
            {"type": "Case", "prompt": "A retail chain's revenue is flat while footfall is up "
             "10%. Structure your diagnosis.",
             "answer": "Revenue = footfall x conversion x basket size. Footfall is up, so "
                       "conversion or basket has fallen - segment by store, category and time "
                       "before proposing anything."},
            {"type": "Aptitude", "prompt": "An investment grows 20% in year one and falls 20% "
             "in year two. What is the net change?",
             "answer": "Down 4%. 1.2 x 0.8 = 0.96 - percentage changes do not cancel."},
            {"type": "Business", "prompt": "A client wants to cut cloud spend 30% without "
             "reducing headcount. Where do you look first?",
             "answer": "Utilisation before rates - idle instances, over-provisioned storage "
                       "tiers, forgotten environments. Committed-use discounts come after "
                       "you know the real baseline."},
            {"type": "Group discussion", "prompt": "Argue both sides: should companies mandate "
             "a return to office?",
             "answer": "Being able to steelman the side you reject scores higher than "
                       "advocating hard for one."},
            {"type": "HR", "prompt": "Consulting involves sustained travel and shifting clients. "
             "What draws you to that?",
             "answer": "Be honest about the trade-off. A candidate who has not thought about "
                       "the cost is a retention risk."},
        ],
    },
    {
        "slug": "wipro",
        "name": "Wipro",
        "sector": "IT Services",
        "difficulty": "Easy",
        "focus": ["Aptitude", "Essay", "Coding basics"],
        "rounds": ["Online assessment", "Written communication", "Technical interview", "HR interview"],
        "blurb": "Includes a written essay section that many candidates skip preparing for "
                 "entirely; the coding bar sits at comfortable fundamentals.",
        "questions": [
            {"type": "Aptitude", "prompt": "In how many ways can the letters of BALLOON be "
             "arranged?",
             "answer": "1260. 7! divided by 2! for the Ls and 2! for the Os."},
            {"type": "Coding", "prompt": "Reverse the words of a sentence while keeping the "
             "words themselves intact.",
             "answer": "Split on whitespace, reverse the list, join. In place: reverse the "
                       "whole string, then reverse each word."},
            {"type": "Essay", "prompt": "Write 200 words on whether automation will reduce "
             "entry-level engineering jobs.",
             "answer": "Graded on structure and grammar, not on the position you take. One "
                       "claim per paragraph, with a concrete example."},
            {"type": "Technical", "prompt": "What is the difference between == and .equals() "
             "in Java?",
             "answer": "== compares references for objects; .equals() compares content when "
                       "overridden. Override hashCode() alongside it or hash collections break."},
            {"type": "HR", "prompt": "Where do you see yourself in three years?",
             "answer": "Tie it to a capability you are building, not to a job title."},
        ],
    },
    {
        "slug": "goldman-sachs",
        "name": "Goldman Sachs",
        "sector": "Finance",
        "difficulty": "Hard",
        "focus": ["Probability", "Data structures", "Market sense"],
        "rounds": ["HackerRank test", "Technical interviews", "Superday"],
        "blurb": "Probability and mental maths carry unusual weight, and answers are expected "
                 "at conversational speed rather than worked out on paper.",
        "questions": [
            {"type": "Probability", "prompt": "Three fair coins are tossed. Given that at least "
             "one is heads, what is the probability all three are?",
             "answer": "1/7. Conditioning removes TTT, leaving 7 equally likely outcomes."},
            {"type": "Probability", "prompt": "You draw two cards from a standard deck without "
             "replacement. Probability both are aces?",
             "answer": "(4/52) x (3/51) = 1/221."},
            {"type": "Coding", "prompt": "Maintain a running median over a stream of numbers.",
             "answer": "Two heaps - a max-heap for the lower half, a min-heap for the upper - "
                       "rebalanced so sizes differ by at most one. O(log n) per insert."},
            {"type": "Market", "prompt": "Interest rates rise sharply. What happens to existing "
             "bond prices, and why?",
             "answer": "They fall. Older bonds pay below the new rate, so their price drops "
                       "until the yield matches what is now available."},
            {"type": "Technical", "prompt": "Why might a hash map degrade to O(n) lookups, and "
             "how do modern implementations mitigate it?",
             "answer": "Collisions collapsing a bucket into a list. Mitigated by treeifying "
                       "large buckets into a balanced tree and by randomised hash seeds."},
        ],
    },
]

_BY_SLUG = {c["slug"]: c for c in COMPANIES}


def _summarise(company: dict) -> dict:
    """Card-level view: everything except the question bodies."""
    return {
        "slug": company["slug"],
        "name": company["name"],
        "sector": company["sector"],
        "difficulty": company["difficulty"],
        "focus": company["focus"],
        "rounds": company["rounds"],
        "blurb": company["blurb"],
        "initials": company["name"][:2].upper(),
        "question_count": len(company["questions"]),
        "round_count": len(company["rounds"]),
    }


def list_companies() -> list[dict]:
    return [_summarise(c) for c in COMPANIES]


def sectors() -> list[str]:
    return sorted({c["sector"] for c in COMPANIES})


def totals() -> dict:
    return {
        "companies": len(COMPANIES),
        "questions": sum(len(c["questions"]) for c in COMPANIES),
        "sectors": len(sectors()),
    }


def get_set(slug: str, unlocked: bool) -> Optional[dict]:
    """
    One company's practice set.

    When `unlocked` is False the withheld questions are dropped here rather
    than hidden in the template - a signed-out visitor reading the network
    response gets the preview and nothing more.
    """
    company = _BY_SLUG.get(slug)
    if company is None:
        return None

    questions = company["questions"]
    visible = questions if unlocked else questions[:GUEST_PREVIEW_QUESTIONS]

    payload = _summarise(company)
    payload.update({
        "unlocked": unlocked,
        "questions": [dict(q) for q in visible],
        "locked_count": 0 if unlocked else len(questions) - len(visible),
    })
    return payload
