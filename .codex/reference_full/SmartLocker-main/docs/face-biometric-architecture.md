# Face Biometrics And Liveness For SmartLocker

## Goal

Build a face verification pipeline for SmartLocker that:

1. Detects that a real person is in front of the camera.
2. Rejects simple presentation attacks such as a printed photo or a phone screen replay.
3. Creates a reusable biometric template instead of storing raw face images as the main identifier.
4. Can be integrated into the existing FastAPI service and access-grant flow.

## Important Constraint

A single static photo is not enough for reliable anti-spoofing.

If the requirement is to distinguish:

- a live face,
- a printed paper photo,
- a face shown on a phone screen,

then the baseline input must be a short capture session, not one uploaded image. The session can be:

- 2 to 5 seconds of video, or
- 3 to 7 frames captured during a guided selfie flow.

The phrase "face map" in this document means a biometric template or embedding derived from the face, not a raw image.

## Recommended Product Flow

### Enrollment

1. User starts identity capture in the web or mobile client.
2. Client captures a short guided selfie session.
3. Backend validates capture quality.
4. Backend runs liveness checks.
5. If liveness passes, backend extracts a face embedding.
6. Backend stores the embedding and metadata, encrypted at rest.
7. Raw images are either deleted immediately or retained only for a short review TTL.

### Verification

1. User starts door access verification.
2. Client captures another short guided selfie session.
3. Backend runs the same liveness checks.
4. Backend extracts a fresh embedding.
5. Backend compares it with the enrolled template.
6. If score is above threshold and the access grant is valid, the system authorizes door opening.

## End-To-End Algorithm

### Stage 1. Capture Quality Gate

Reject low-quality input before liveness and recognition:

- face detected exactly once,
- minimum face size in frame,
- face centered,
- yaw, pitch, roll inside allowed range,
- enough sharpness,
- enough lighting,
- no heavy occlusion,
- no extreme crop.

Output:

- `quality_pass: bool`
- `quality_score: float`
- normalized face crop
- landmarks

### Stage 2. Passive Liveness

Use frame-level anti-spoofing signals that do not require user action:

- moire or screen-refresh artifacts,
- specular highlight patterns typical for displays,
- print texture and paper flatness cues,
- depth inconsistency inferred from multi-frame parallax,
- eye region reflectance anomalies,
- skin micro-texture,
- face-boundary artifacts near hair, ears, and jawline,
- background-motion inconsistency relative to the face plane.

Output:

- `passive_liveness_score: float`
- `spoof_type_hint: live | print | screen | unknown`

### Stage 3. Active Liveness

Add at least one challenge because passive liveness alone is rarely enough in production:

- blink twice,
- turn head left then right,
- move closer slightly,
- smile,
- follow a dot on screen.

The system verifies:

- the instructed action happened,
- timing is natural,
- motion is 3D-consistent,
- landmarks evolve smoothly across frames.

Output:

- `challenge_pass: bool`
- `challenge_score: float`

### Stage 4. Face Normalization

For frames that passed quality and liveness:

- detect landmarks,
- align eyes and nose,
- crop to canonical face region,
- normalize color and scale,
- optionally choose the best frame or aggregate several frames.

### Stage 5. Template Extraction

Generate a face embedding using a face-recognition model.

Recommended approach:

- extract embedding from 1 to 3 best frames,
- average embeddings,
- L2-normalize the final vector.

Output:

- `embedding: vector<float>`
- `embedding_model_version`

### Stage 6. Matching

Compare probe embedding with enrolled embedding:

- cosine similarity or Euclidean distance,
- threshold tuned on your own data,
- stricter threshold for first unlock,
- optional secondary factor for risky cases.

Output:

- `match_score: float`
- `match_pass: bool`

### Stage 7. Decision Engine

Final decision should not depend on one score only.

Example rule:

- allow if `quality_pass = true`
- and `passive_liveness_score >= P1`
- and `challenge_score >= P2`
- and `match_score >= P3`
- and access grant is active

Otherwise:

- deny,
- or request recapture,
- or escalate to manual review.

## Minimal Production Decision Logic

For V1, use this sequence:

1. Detect face and landmarks.
2. Reject poor-quality samples.
3. Run passive liveness on several frames.
4. Require a simple active challenge.
5. Build one fused embedding.
6. Compare against stored template.
7. Return a structured decision with scores and reasons.

This is the minimum acceptable architecture if the system must reject phone-screen and paper-photo attacks.

## Why Static Photo Only Is Weak

If the input is only one uploaded image:

- a high-resolution screen replay can look realistic,
- a printed photo can survive simple texture checks,
- there is no trustworthy motion or depth signal,
- challenge-response is impossible.

So if the business requirement insists on "one photo only", then the honest answer is:

- face matching is possible,
- robust liveness is not.

## Data Objects To Introduce

Add new persistence entities for biometrics. Do not store raw face images as the primary identity object.

### `biometric_profiles`

- `id`
- `user_id`
- `status`
- `embedding_encrypted`
- `embedding_model_version`
- `liveness_policy_version`
- `created_at`
- `updated_at`

### `biometric_sessions`

- `id`
- `user_id`
- `session_type` (`enroll` or `verify`)
- `status`
- `challenge_type`
- `challenge_payload`
- `quality_score`
- `passive_liveness_score`
- `challenge_score`
- `match_score`
- `decision`
- `failure_reason`
- `created_at`
- `completed_at`

### `biometric_audit_events`

- `id`
- `session_id`
- `event_type`
- `payload_json`
- `created_at`

## Suggested API Contracts

### Enrollment

`POST /api/v1/biometrics/enrollment/session`

Creates a session and challenge.

`POST /api/v1/biometrics/enrollment/{session_id}/frames`

Uploads frames or video chunk metadata.

`POST /api/v1/biometrics/enrollment/{session_id}/complete`

Runs quality, liveness, embedding extraction, and template save.

### Verification

`POST /api/v1/biometrics/verification/session`

Creates a verification session and challenge.

`POST /api/v1/biometrics/verification/{session_id}/frames`

Uploads frames or video chunk metadata.

`POST /api/v1/biometrics/verification/{session_id}/complete`

Returns decision payload:

- `decision`
- `quality_score`
- `passive_liveness_score`
- `challenge_score`
- `match_score`
- `reasons`

## Integration With Current SmartLocker Service

The current codebase already has:

- FastAPI app bootstrap,
- SQLAlchemy models,
- auth users,
- access grants,
- user dashboard.

Recommended integration points:

### Backend module

Create `app/modules/biometrics/` with:

- `routes.py`
- `service.py`
- `schemas.py`
- `liveness.py`
- `recognition.py`
- `storage.py`

### App wiring

Register the biometrics router in the main app and initialize a biometrics service in app state if needed.

### Database

Extend `app/db/models.py` with biometric profile and session models.

### Access flow

Tie verification result to `AccessGrantModel`:

- access grant says user may open door in time window,
- biometrics says the claimant is the enrolled person and is live,
- unlock only when both pass.

## Suggested Internal Interfaces

```python
class CaptureQualityResult(BaseModel):
    passed: bool
    score: float
    reasons: list[str]


class LivenessResult(BaseModel):
    passed: bool
    passive_score: float
    challenge_score: float
    spoof_type_hint: str | None = None
    reasons: list[str]


class MatchResult(BaseModel):
    passed: bool
    score: float
    threshold: float
    reasons: list[str]
```

```python
class BiometricsService:
    def enroll(self, session_id: str, frames: list[bytes]) -> dict: ...
    def verify(self, session_id: str, frames: list[bytes]) -> dict: ...
```

## Security And Privacy Requirements

Because this system processes biometric personal data:

- encrypt embeddings at rest,
- separate templates from session media,
- keep raw captures for the shortest feasible period,
- add explicit consent flow,
- log every enrollment and verification decision,
- add rate limiting and replay protection,
- version every model and threshold,
- support template revocation and re-enrollment.

For Russian and international deployments, biometric data handling must be reviewed as a regulated personal-data workflow before production.

## V1 Technical Recommendation

For an initial production-friendly version:

1. Web client or mobile client captures 3 to 5 seconds of selfie video.
2. Backend samples several frames.
3. Backend performs:
   - face detection,
   - landmark extraction,
   - quality gate,
   - passive liveness,
   - one active challenge check,
   - embedding extraction,
   - score fusion.
4. Backend stores only encrypted embedding and audit data.
5. Door opening requires both active access grant and successful biometric verification.

## Rollout Plan

### Phase 1

- add DB entities,
- add API contracts,
- add session lifecycle,
- store capture metadata and stub decisions,
- wire dashboard or client flow.

### Phase 2

- integrate face detector and landmark model,
- integrate embedding model,
- integrate passive liveness model,
- add active challenge orchestration.

### Phase 3

- calibrate thresholds on real data,
- measure false accept and false reject rates,
- add risk-based fallbacks,
- add manual review tooling for failed sessions.

## Practical Decision

If SmartLocker must really block phone-screen and paper-photo spoofing, the product requirement should be updated from:

- "build a face map from one photo"

to:

- "build a face template from a guided short selfie session with liveness verification"

That change is the difference between a demo and a production-capable access-control system.
