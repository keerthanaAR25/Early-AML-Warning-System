// Runs once in the main process BEFORE the test workers start, so every worker inherits India time (UTC+5:30).
// A date shown a day early in that zone is a real defect that tests running in UTC cannot see.
export default function setup() {
  process.env.TZ = "Asia/Kolkata";
}
