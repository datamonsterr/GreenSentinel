# Dialogue EDA — MultiWOZ 2.2 taxi + SGD structural reference (Issue #250)

Source: `data/raw/multiwoz` (MIT) + `data/raw/sgd_dialogue` (CC BY-SA 4.0, EDA-ONLY).
Script: [scripts/eda_dialogues.py](../../scripts/eda_dialogues.py).
Aggregates: [notebooks/dialogues/profile.json](../../notebooks/dialogues/profile.json).
`data/raw/` is git-ignored; no raw text redistributed. Snippets below are short
anonymized passenger utterances from the MIT-licensed MultiWOZ taxi subset only;
no SGD utterances are quoted (ShareAlike).

## A) MultiWOZ 2.2 taxi subset

10,437 dialogues total; **1,872 (17.9%) include the taxi service**, of which
**430 are taxi-only**. All stats below cover the 1,872 taxi dialogues (15,327
passenger + 15,327 system utterances).

### Turn-count distribution (per dialogue, user+system turns)

| min | p05 | p25 | p50 | p75 | p95 | max | mean |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 4 | 6 | 12 | **16** | 20 | 26 | 42 | 16.4 |

User turns per dialogue: p50 **8**, p25–p75 6–10, max 21.

### Passenger utterance length

| | min | p05 | p25 | p50 | p75 | p95 | max | mean |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| chars | 9 | 24 | 38 | **56** | 79 | 122 | 195 | 61.7 |
| words | 2 | 5 | 8 | **11** | 16 | 24 | 34 | 12.3 |

System utterances are longer (words p50 15, p95 28). Calibration prior for
synthetic driver–customer chat: passenger turns cluster at **8–16 words**,
rarely above 25; dialogues run **12–20 turns** total.

### Taxi-booking slot patterns (belief-state `slot_values` mentions)

| Slot | Mentions |
|---|---:|
| `taxi-destination` | 5,224 |
| `taxi-departure` | 5,211 |
| `taxi-leaveat` | 2,836 |
| `taxi-arriveby` | 2,267 |

Pickup/dropoff appear in nearly every taxi dialogue; explicit time constraints
(`leaveat`/`arriveby`) in roughly half. No phone/car-type slots in belief state —
car type and contact number are negotiated in surface text (see snippets).

### Complaint / cancellation utterances (tone/length calibration)

Explicit taxi cancellations are **rare** in MultiWOZ; the closest real matches
are booking modifications, wrong-info corrections, and missed-detail complaints.
Each is 13–30 words, polite-register, indirect ("I was never given…",
"let's back up", "change my mind") — no profanity or all-caps in the subset:

1. "I was never given the car type and contact number for my taxi, could you please provide them?" (18w)
2. "You know what I change my mind. I'll book later. I still need a taxi from University Arms Hotel leaving at 14:15 to the Ugly Duckling." (26w)
3. "I'm sorry. I gave you the wrong information. I need to leave from the Fitzwilliam Museum and arrive at Royal Standard by 07:45." (23w)
4. "I'm not quite ready to make a reservation, but can you tell me their postcode and phone number so I can ring them later if I change my mind?" (29w)
5. "I'm sorry, let's back up. We'll worry about the taxi later. First, can you help me find a college on the west side of town?" (25w)
6. "I want to leave the college by 24:00, and can I get the contact number and car type please so I don't get in the wrong car?" (27w)
7. "That's because you never got back to me, you forgot first. I want to go somewhere in the south but I'm not familiar with the town, what do you recommend?" (30w)
8. "I'm looking for a proper hotel, please. If it had free wifi, well, I wouldn't complain about that either." (19w)

Implication for synthesis: cancellation/dispute talk in this register is
polite + corrective, not abusive; ERR-01 cancellation dialogue should follow
the modify/correct pattern (new pickup, new time, "wrong information") rather
than inventing aggressive tone without evidence.

## B) SGD structural reference + domain overlap

22,825 dialogues (16,142/2,482/4,201 train/dev/test). Overall turns p50 **20**
(p25–p75 16–24); user utterance words p50 **7** (shorter than MultiWOZ's 11).
Ride-relevant subset (`RideSharing_1/2`, `Buses_*`, `Flights_1`): **7,144**
dialogues, turns p50 **22**, user words p50 **7**.

Domain-overlap comparison vs our driver–customer ride chat:

- Covered by analogy: origin/destination slots (`Flights_1:origin_city`,
  `destination_city`), time slots (`outbound_departure_time`,
  `Restaurants_1:time`), vehicle choice (`RentalCars_1:type`,
  `RideSharing_2:ride_type` ≈ car-type negotiation), price-insensitive booking flow.
- Missing in SGD: driver identity/contact-number exchange, pickup-point
  negotiation at street level, cancellation/dispute acts, fare haggling —
  all present in MultiWOZ taxi text instead.
- Structural prior adopted: slot-driven request/inform rhythm with
  explicit time + endpoint slots; SGD's shorter user turns (p50 7w) are a
  lower bound, MultiWOZ taxi (p50 11w) the closer match for ride chat.

Verdict: keep SGD as structural reference only (weak ride-hailing match +
ShareAlike); anchor synthetic conversation text on MultiWOZ taxi acts with
Vietnamese surface forms generated separately.

## Reproduce

```bash
.venv/bin/python scripts/eda_dialogues.py  # reads data/raw, writes notebooks/dialogues/profile.json
```
