# AUT-6 WP2 verify-first (ruling r2 A8), 2026-10-08

Verdict: **V-a FAILED. STOP.** Replace-by-sequence-id and DELETE of a scheduled ntfy.sh message
did NOT cancel the pending message in three independent live runs. The Path B dead-man design
(re-publish to move the alarm) cannot work as ruled; it goes back to review. No production code
was written. Scratch topics are random `claude-aut6-<uuid4hex>` and are not secrets; the
production topic was never read or contacted.

Method: curl against https://ntfy.sh, anonymous, scratch topic. Poll:
`GET /<scratch>/json?poll=1&since=all` after the `At`/`In` instant had passed by >= 30-90 s.
Expected by the vendor docs ("Updating scheduled notifications", "Canceling scheduled
notifications"): exactly one `message` event for seqA, with the SECOND text; none for the deleted seqB.

## Run 1 (`At: <unix>` header, +60 s), topic claude-aut6-fb8c7c0e4385461cba61caaf5cd90417
publish (POST /<t>/seqA At=1791492631 "FIRST-MESSAGE"), (POST /<t>/seqA same At "SECOND-MESSAGE"),
(POST /<t>/seqB same At "THIRD-SHOULD-BE-DELETED"), (DELETE /<t>/seqB -> HTTP 200, event message_delete).
Poll after delivery time (raw):
```
{"id":"eIdtgsmCYQsb","sequence_id":"seqB","time":1791492571,"expires":1791535771,"event":"message_delete","topic":"claude-aut6-fb8c7c0e4385461cba61caaf5cd90417"}
{"id":"bP2dMfCon8aT","sequence_id":"seqA","time":1791492631,"expires":1791535831,"event":"message","topic":"claude-aut6-fb8c7c0e4385461cba61caaf5cd90417","title":"first","message":"FIRST-MESSAGE"}
{"id":"39kdGOEe6URT","sequence_id":"seqA","time":1791492631,"expires":1791535831,"event":"message","topic":"claude-aut6-fb8c7c0e4385461cba61caaf5cd90417","title":"second","message":"SECOND-MESSAGE"}
{"id":"uYk69FfmY9mW","sequence_id":"seqB","time":1791492631,"expires":1791535831,"event":"message","topic":"claude-aut6-fb8c7c0e4385461cba61caaf5cd90417","message":"THIRD-SHOULD-BE-DELETED"}
```
Result: BOTH seqA messages delivered (not one), and the DELETEd seqB was delivered.

## Run 2 (same, `At: +75 s`), topic claude-aut6-baed3654e5354b32a58eca2427c9553b
Pending-list probe (`...&scheduled=1`) returned empty after each publish (not informative).
Poll after delivery (raw):
```
{"id":"FGLbIneiaIkL","sequence_id":"seqB","time":1791492663,"expires":1791535863,"event":"message_delete","topic":"claude-aut6-baed3654e5354b32a58eca2427c9553b"}
{"id":"ew5noKFmhaKB","sequence_id":"seqA","time":1791492737,"expires":1791535937,"event":"message","topic":"claude-aut6-baed3654e5354b32a58eca2427c9553b","title":"first","message":"FIRST-MESSAGE"}
{"id":"LXNuCZPuUOZw","sequence_id":"seqA","time":1791492737,"expires":1791535937,"event":"message","topic":"claude-aut6-baed3654e5354b32a58eca2427c9553b","title":"second","message":"SECOND-MESSAGE"}
{"id":"WWPNu5Um07aG","sequence_id":"seqB","time":1791492737,"expires":1791535937,"event":"message","topic":"claude-aut6-baed3654e5354b32a58eca2427c9553b","message":"THIRD"}
```
Result: same failure.

## Run 3 (`In: 75s` header, as in the vendor's dead-man example; plus `X-Sequence-ID` header form), topic claude-aut6-be5f03479e7e4070b40c8a685acb8dc2
Poll after delivery (raw):
```
{"id":"F4FcAL6VzTbD","sequence_id":"seqB","time":1791492754,"expires":1791535954,"event":"message_delete","topic":"claude-aut6-be5f03479e7e4070b40c8a685acb8dc2"}
{"id":"8EQbli7aftNx","sequence_id":"seqA","time":1791492828,"expires":1791536028,"event":"message","topic":"claude-aut6-be5f03479e7e4070b40c8a685acb8dc2","title":"first","message":"FIRST-MESSAGE"}
{"id":"4K23c9Xw6pXj","sequence_id":"seqA","time":1791492829,"expires":1791536029,"event":"message","topic":"claude-aut6-be5f03479e7e4070b40c8a685acb8dc2","title":"second","message":"SECOND-MESSAGE"}
{"id":"Fujdx7pRaVCe","sequence_id":"seqC","time":1791492829,"expires":1791536029,"event":"message","topic":"claude-aut6-be5f03479e7e4070b40c8a685acb8dc2","message":"C-FIRST"}
{"id":"CQzhYyx01Stq","sequence_id":"seqC","time":1791492829,"expires":1791536029,"event":"message","topic":"claude-aut6-be5f03479e7e4070b40c8a685acb8dc2","message":"C-SECOND"}
{"id":"D59oivuBCOZi","sequence_id":"seqB","time":1791492829,"expires":1791536029,"event":"message","topic":"claude-aut6-be5f03479e7e4070b40c8a685acb8dc2","message":"THIRD"}
```
Result: same failure for the path form (seqA), the header form (seqC) and DELETE (seqB). So it is
not an `At` vs `In` or path vs header artefact. Server health at the time: `{"healthy":true}`;
`/v1/config` returned no version or limit fields.

## V-b: anonymous limits on the public server (docs.ntfy.sh/publish "Limitations")
- Daily messages: 250 on ntfy.sh (visitor-based). Our load (~30 publishes/day) is far inside it,
  but a 3-tier schedule (two sequence ids re-armed by each of ~24 canaries/day = ~48 schedule posts
  plus ~30 deliveries) is ~80/day, still inside.
- Requests: 60 burst, refill 1 per 5 s. Message length 4096 B. Title <= 1 KB.
- Daily bandwidth 200 MB (poll replays count).
- Scheduled delay: min 10 s, max 3 days (`message-delay-limit`). No separate scheduled-message cap is documented.
- Cache/retention: 12 h default; a scheduled message stays cached until delivery time + 12 h
  (observed `expires` = At + 43200 s on every message above).
- Anonymous topics have no auth: anyone with the topic can read, publish, replace or DELETE (accepted risk A7).
- The documented replace/cancel behaviour is contradicted by live behaviour (above); that, not any
  limit, is the blocker.

## Consequence
Without working replace/cancel on the receiver, each re-arm leaves the earlier alarm pending, so
every day's alarm fires regardless of liveness. Path B as ruled is unimplementable on anonymous
ntfy.sh. Options for review (not decided here): a self-hosted/authenticated ntfy topic, a different
absence service (e.g. a healthchecks-style dead-man URL), or `Path A` receiver-side rule elsewhere.
