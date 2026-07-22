# Affective Incident Learning

Status: implemented bounded backend baseline (2026-07-22)

## Purpose

Alpecca now has a computational analogue of incident-conditioned affect and
recovery. It is designed to let verified mistakes influence later caution,
reflection, and bounded improvement without claiming that software has human
trauma, PTSD, consciousness, or a biological emotional experience.

This is not a prompt persona. The state is persisted in SQLite, computed without
an LLM, exposed for creator inspection, and passed into the existing seven-role
Soul snapshot.

## Research Translation

The implementation combines three narrow ideas:

1. **Appraisal dynamics.** EMA models emotion as repeated appraisal of an
   interpreted relationship between agent and environment, followed by coping
   and re-appraisal. Alpecca therefore computes activation from severity,
   controllability, and prediction error rather than assigning a canned label.
2. **Associative learning and prediction error.** A verified recurrence raises
   the learned cue response. An incident is never inferred from generated text.
3. **Extinction/safety learning.** Successful retries create a competing safety
   history that lowers activation. They do not delete the incident. Exact cue
   matching and recovery prevent the broad overgeneralization associated with
   pathological fear models.

Primary open-access inputs:

- Marsella and Gratch, *EMA: A Process Model of Appraisal Dynamics*:
  https://www.ccs.neu.edu/~marsella/publications/pdf/MarsellaCSR09.pdf
- Morey et al., *Fear learning circuitry is biased toward generalization of
  fear associations in PTSD*: https://pmc.ncbi.nlm.nih.gov/articles/PMC5068591/
- Kredlow et al., *Laboratory models of posttraumatic stress disorder: the
  elusive bridge to translation*:
  https://pmc.ncbi.nlm.nih.gov/articles/PMC9167267/

These papers motivate a simulation architecture; they do not establish that an
AI system experiences human emotion or trauma.

## Runtime Contract

- `alpecca/incident_learning.py` owns the append/update ledger and exact-cue
  assessment.
- An incident requires a source, stable cue family, bounded factual summary,
  severity, controllability, and prediction error.
- Generated prose cannot create an incident.
- Cue assessment uses exact code-supplied cue families, not semantic matching
  over conversation. This deliberately prevents fear spreading to merely
  similar words.
- Repeated verified failures raise activation and reduce recovery.
- Verified safe outcomes lower activation and raise recovery. Sufficient safety
  evidence marks the incident integrated while preserving its history.
- Every transition attempts a content-minimized `CognitionObservation` audit.
- Current activation influences measured unease and enters `soul.Snapshot`.
  Feeler may prioritize stabilization; Reflector may integrate the event; and
  Improver may propose one bounded prevention experiment. Existing approval and
  actuation boundaries remain in force.
- Prompt narration states that the cue is caution, not proof of present failure.

## Initial Automatic Evidence

Measured high or critical host-resource pressure records the stable
`host-resource-pressure` cue. A later measured return to normal creates a safe
outcome. A live chat turn that exceeds the server's bounded deadline records a
`chat-reply-stall` cue; the next completed live reply creates safety evidence.
These transitions use server-observed outcomes and cannot be triggered by model
narration.

Other subsystems should integrate only at their verified outcome boundary. For
example, Discord voice should record a receive timeout only after its transport
and transcription state prove that timeout, then record safety after a complete
receive-transcribe-reply cycle. Raw audio, messages, credentials, and screenshots
must not be copied into the incident ledger.

## Creator Inspection

- `GET /affect/incidents` lists bounded evidence, activation, recovery, and the
  current Soul signal.
- `POST /affect/incidents` records creator-verified evidence.
- `POST /affect/incidents/{id}/outcome` records a verified safe retry or
  recurrence.

All routes require the existing creator authorization. They do not grant new
computer-use or system-modification authority.
