# AI Usage Log

We expect you to use AI tools. We are not testing whether you can avoid them — we are
testing whether you understand and own what you ship. Fill this in honestly as you work.
A thin or evasive log is a worse signal than heavy, well-understood AI use.

---

## 1. Where did you use AI?

For each significant use, give: what you asked, what it produced, and what you changed or
rejected and why.

- **Pipeline architecture and stage design:** I used AI to help structure the pipeline into five stages and define the data flow between them. The AI suggested using dataclasses for inter-stage models and SQLite for state management. I accepted the dataclass approach because it keeps things lightweight without ORM overhead. I chose SQLite for idempotency state because it requires zero external configuration—important for a Docker-based submission.

- **Entity resolution strategy:** I asked the AI to help design a deduplication approach. It initially suggested fuzzy string matching (Levenshtein distance), but I chose a deterministic two-key approach (company name prefix + domain root with union-find) instead. The fuzzy approach required threshold tuning and risked false positives; the two-key method leverages the domain signal which is highly reliable for this dataset.

- **CSV field cleaning functions:** I used AI to help write the parsing logic for employee counts (handling "11-50", "~42", "1000+", "10 to 210" formats) and date parsing (6+ formats). I reviewed and tested each function against actual data samples from the CSV. I corrected the date format priority order — the AI had DD/MM/YYYY before MM/DD/YYYY, but the dataset uses US-style dates more often.

- **Async enrichment client:** I used AI to scaffold the httpx async client with semaphore-based rate limiting. I adjusted the semaphore limit from 8 (which the AI suggested to match the API limit) down to 6 to give safety margin, since burst patterns could briefly exceed 8 even with a semaphore.

- **Scoring formula:** I designed the scoring weights and signal interpretation myself, then used AI to help implement the per-signal scoring functions. The AI suggested equal weights; I changed to a weighted system prioritising employee count and revenue band because those are the strongest B2B qualification signals.

## 2. What did you NOT understand at first, and how did you resolve it?

- The relationship between the API's rate limit (8 req/s) and the semaphore concurrency limit wasn't obvious at first. I thought setting the semaphore to 8 would be safe, but realised that if all 8 requests completed in ~80ms (the minimum latency), the next batch would fire within the same second, exceeding the limit. I resolved this by reducing the semaphore to 6 and relying on the natural latency variation (80-650ms) to spread requests across the second.

## 3. One decision you made against what the AI suggested

What did it recommend, what did you do instead, and why?

- The AI recommended using fuzzy string matching (Jaro-Winkler similarity with a 0.85 threshold) for entity resolution. I chose a deterministic two-key approach instead (first two meaningful words of company name + domain root, combined via union-find). My reasoning: fuzzy matching requires careful threshold tuning — too low and you merge unrelated companies, too high and you miss duplicates. The two-key approach is predictable, debuggable, and the dataset's naming patterns (same company base name with different suffixes) are perfectly captured by prefix extraction. The domain root provides a second strong signal that fuzzy matching on names alone would miss.

## 4. If your reviewer asked "why this approach?" about the hardest part of your
##    pipeline, what would you say — in your own words?

- The hardest part was entity resolution. The core challenge is: how do you know two records refer to the same company when the names are "Northwind Logistics Partners Inc" and "northwind logistics global inc"? My approach extracts the first two meaningful words (ignoring suffixes like Inc, LLC, Group, Partners, International) to get a canonical key: both become "northwind_logistics". Records sharing that key are unioned together. I also union by domain root — if two records share "northwindlogistics" as their domain prefix, they're the same entity even if one is called "Northwind Logistics" and the other "NW Logistics Corp". The union-find data structure handles transitive merges (A matches B, B matches C, so A-B-C are all one entity). When merging, I pick the shortest name (least noisy), the most common domain, median employee count, and most recent date. This is deterministic, requires no threshold tuning, and covers every duplicate pattern I found in the actual data.
