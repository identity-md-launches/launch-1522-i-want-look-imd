import test from "node:test";
import assert from "node:assert/strict";
import { parseRadarObservation } from "../src/radar-data";

const empty = () => ({ sourceRetrievedAt: null, seats: [], relationships: [], ethereumRelationships: [], launches: [], sources: [], conflict: false, conflicts: [], dataQuality: { available: false, stale: false, seatDetailsComplete: true } });

test("An unavailable optional Radar response is a valid empty observation", () => {
  const value = empty();
  assert.deepEqual(parseRadarObservation(value), value);
});
test("Malformed enrichment is rejected before React renders it", () => {
  for (const value of [null, {}, { ...empty(), seats: "bad" }, { ...empty(), sourceRetrievedAt: -1 }, { ...empty(), dataQuality: {} }, { ...empty(), launches: [{ rewards: null }] }]) {
    assert.throws(() => parseRadarObservation(value), /Malformed enrichment response/);
  }
});
test("Source evidence URLs and response hashes are validated, including recovery-file input", () => {
  const evidence = { sourceUrl: "https://www.imdradar.site/api/feed?view=swarm", sourceRetrievedAt: 1791907000, responseId: 1, responseHash: "ab".repeat(32), dataQuality: { stale: false } };
  assert.equal(parseRadarObservation({ ...empty(), sources: [evidence] }).sources.length, 1);
  for (const sourceUrl of ["javascript:alert(1)", "https://attacker.invalid/", "https://www.imdradar.site/api/feed?view=swarm&extra=1"]) {
    assert.throws(() => parseRadarObservation({ ...empty(), sources: [{ ...evidence, sourceUrl }] }));
  }
  assert.throws(() => parseRadarObservation({ ...empty(), sources: [{ ...evidence, responseHash: "invalid" }] }));
});
