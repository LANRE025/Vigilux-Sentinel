// ============================================================
// Mock data for demo mode. Mirrors the backend seed regions
// (backend/data/seed_regions.py) and a sample FleetReport
// (backend/examples/sample_fleet_report.json), plus a per-region
// lat/lon so the Signal Console renders a full board offline.
// ============================================================

export const AGENTS_ORDER = [
  'data_steward',
  'risk_assessor',
  'historian',
  'curator',
]

// 10 hand-authored seed regions, with coordinates + key signals.
export const MOCK_REGIONS = [
  { region_id: 'region-lusaka-01', country: 'Zambia', lat: -15.39, lon: 28.32, days_since_survey: 47, admissions_pct_change: 21.0, funding_pct_of_avg: 41.0 },
  { region_id: 'region-accra-01', country: 'Ghana', lat: 5.6, lon: -0.19, days_since_survey: 31, admissions_pct_change: 17.0, funding_pct_of_avg: 52.0 },
  { region_id: 'region-kathmandu-01', country: 'Nepal', lat: 27.72, lon: 85.32, days_since_survey: 88, admissions_pct_change: 13.0, funding_pct_of_avg: 63.5 },
  { region_id: 'region-kampala-01', country: 'Uganda', lat: 0.35, lon: 32.58, days_since_survey: 35, admissions_pct_change: 8.0, funding_pct_of_avg: 84.0 },
  { region_id: 'region-nairobi-01', country: 'Kenya', lat: -1.29, lon: 36.82, days_since_survey: 15, admissions_pct_change: 6.0, funding_pct_of_avg: 96.0 },
  { region_id: 'region-jakarta-01', country: 'Indonesia', lat: -6.21, lon: 106.85, days_since_survey: 20, admissions_pct_change: 4.0, funding_pct_of_avg: 118.0 },
  { region_id: 'region-tijuana-01', country: 'Mexico', lat: 32.51, lon: -117.04, days_since_survey: 27, admissions_pct_change: 3.0, funding_pct_of_avg: 104.0 },
  { region_id: 'region-manaus-01', country: 'Brazil', lat: -3.12, lon: -60.02, days_since_survey: 9, admissions_pct_change: -2.0, funding_pct_of_avg: 121.0 },
  { region_id: 'region-lima-01', country: 'Peru', lat: -12.05, lon: -77.04, days_since_survey: 12, admissions_pct_change: 1.0, funding_pct_of_avg: 98.0 },
  { region_id: 'region-bangalore-01', country: 'India', lat: 12.97, lon: 77.59, days_since_survey: 6, admissions_pct_change: 0.0, funding_pct_of_avg: 99.0 },
]

// A representative FleetReport the sweep resolves to in demo mode.
export const MOCK_REPORT = {
  run_id: 'demo-9f3c1e2a7b4d',
  started_at: '2026-08-31T00:00:00.000+00:00',
  completed_at: '2026-08-31T00:00:02.100+00:00',
  regions_evaluated: 5,
  regions_flagged: 3,
  assessments: [
    {
      region_id: 'region-lusaka-01',
      country: 'Zambia',
      risk_level: 'Urgent',
      explanation:
        'Admissions up 21% over the prior period, funding at 41% of the regional average and staffing below 30.',
      confidence: 'High',
      signals_used: ['admissions_pct_change', 'funding_pct_of_avg'],
      days_since_survey: 47,
      assessed_at: '2026-08-31T00:00:00.600+00:00',
      trend: {
        region_id: 'region-lusaka-01',
        previous_risk_level: 'Watch',
        current_risk_level: 'Urgent',
        trend_direction: 'worsening',
        runs_compared: 6,
        note: 'Risk escalated from Watch to Urgent since the last assessment.',
      },
    },
    {
      region_id: 'region-accra-01',
      country: 'Ghana',
      risk_level: 'Urgent',
      explanation: 'Rising admissions trend with funding at roughly half of the regional average.',
      confidence: 'Medium',
      signals_used: ['admissions_pct_change', 'funding_pct_of_avg'],
      days_since_survey: 31,
      assessed_at: '2026-08-31T00:00:00.800+00:00',
      trend: {
        region_id: 'region-accra-01',
        previous_risk_level: 'Watch',
        current_risk_level: 'Urgent',
        trend_direction: 'worsening',
        runs_compared: 4,
        note: 'Risk escalated from Watch to Urgent since the last assessment.',
      },
    },
    {
      region_id: 'region-kampala-01',
      country: 'Uganda',
      risk_level: 'Watch',
      explanation: 'Admissions +8%; staffing close to the fleet floor.',
      confidence: 'Medium',
      signals_used: ['admissions_pct_change'],
      days_since_survey: 35,
      assessed_at: '2026-08-31T00:00:01.100+00:00',
      trend: {
        region_id: 'region-kampala-01',
        previous_risk_level: 'Stable',
        current_risk_level: 'Watch',
        trend_direction: 'worsening',
        runs_compared: 4,
        note: 'Risk escalated from Stable to Watch since the last assessment.',
      },
    },
    {
      region_id: 'region-nairobi-01',
      country: 'Kenya',
      risk_level: 'Watch',
      explanation: 'Admissions +6% over the prior period with funding slightly below average.',
      confidence: 'Medium',
      signals_used: ['admissions_pct_change', 'funding_pct_of_avg'],
      days_since_survey: 15,
      assessed_at: '2026-08-31T00:00:01.400+00:00',
      trend: {
        region_id: 'region-nairobi-01',
        previous_risk_level: 'Urgent',
        current_risk_level: 'Watch',
        trend_direction: 'improving',
        runs_compared: 7,
        note: 'Risk eased from Urgent to Watch since the last assessment.',
      },
    },
    {
      region_id: 'region-bangalore-01',
      country: 'India',
      risk_level: 'Stable',
      explanation: 'No concerning signals: flat admissions, funding and staffing adequate.',
      confidence: 'High',
      signals_used: [],
      days_since_survey: 6,
      assessed_at: '2026-08-31T00:00:01.900+00:00',
      trend: {
        region_id: 'region-bangalore-01',
        previous_risk_level: null,
        current_risk_level: 'Stable',
        trend_direction: 'first_observation',
        runs_compared: 1,
        note: 'First fleet assessment recorded for region-bangalore-01; baseline is Stable.',
      },
    },
  ],
  missing_region_ids: [],
}

// Per-agent telemetry the status rail shows after a sweep.
export const MOCK_TIMINGS = [
  { agent: 'data_steward', duration_ms: 240, regions_processed: 10 },
  { agent: 'risk_assessor', duration_ms: 1180, regions_processed: 5 },
  { agent: 'historian', duration_ms: 320, regions_processed: 5 },
  { agent: 'curator', duration_ms: 260, regions_processed: 5 },
]

export function displayName(region) {
  return `${region.country}${region.disease ? ` / ${region.disease}` : ''}`
}

export function formatCoord(v, isLat) {
  const n = Math.abs(v).toFixed(2)
  if (isLat) return `${v < 0 ? 'S' : 'N'}${n}`
  return `${v < 0 ? 'W' : 'E'}${n}`
}
