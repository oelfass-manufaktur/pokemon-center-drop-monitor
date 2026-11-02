// Private Google Apps Script. The only network destination is this repository's GitHub workflow.
const UPC_WORKFLOW = 'https://api.github.com/repos/oelfass-manufaktur/pokemon-center-drop-monitor/actions/workflows/monitor.yml';
const TOKEN_PROPERTY = 'GITHUB_TIMER_TOKEN';

function githubRequest_(suffix, options) {
  const token = PropertiesService.getScriptProperties().getProperty(TOKEN_PROPERTY);
  if (!token) throw new Error('Skripteigenschaft GITHUB_TIMER_TOKEN fehlt.');
  const response = UrlFetchApp.fetch(UPC_WORKFLOW + suffix, Object.assign({}, options, {
    headers: {Authorization: 'Bearer ' + token, Accept: 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28'},
    followRedirects: false, muteHttpExceptions: true
  }));
  const code = response.getResponseCode();
  if (code < 200 || code >= 300) throw new Error('GitHub HTTP ' + code);
  return response;
}

function zeitgeberEinrichten() {
  // Read-only preflight. Installing the clock does not immediately dispatch a workflow.
  const workflow = JSON.parse(githubRequest_('', {method: 'get'}).getContentText());
  if (workflow.state !== 'active') throw new Error('Der Workflow ist nicht aktiv.');
  const existing = ScriptApp.getProjectTriggers().some(t => t.getHandlerFunction() === 'pruefungPlanen');
  if (!existing) ScriptApp.newTrigger('pruefungPlanen').timeBased().everyMinutes(10).create();
  console.log('10-Minuten-Zeitgeber eingerichtet.');
}

function imPruefzeitfenster_() {
  // 13:00 bis unmittelbar vor 02:00 in Deutschland, inkl. Sommer-/Winterzeit.
  const hour = Number(Utilities.formatDate(new Date(), 'Europe/Berlin', 'H'));
  return hour >= 13 || hour < 2;
}

function pruefungPlanen() {
  if (!imPruefzeitfenster_()) {
    console.log('Außerhalb 13:00–02:00 Europe/Berlin: kein GitHub-Dispatch.');
    return;
  }
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(0)) return;
  try {
    const properties = PropertiesService.getScriptProperties();
    const cutoff = Date.now() - 8 * 60000;
    if (Number(properties.getProperty('LAST_DISPATCH_MS') || 0) >= cutoff) return;
    const runs = JSON.parse(githubRequest_('/runs?branch=main&event=schedule&per_page=3', {method: 'get'}).getContentText());
    const fresh = runs.workflow_runs.some(run => Date.parse(run.run_started_at || run.created_at) >= cutoff
      && (run.conclusion === 'success' || run.status === 'in_progress'));
    if (fresh) return;
    githubRequest_('/dispatches', {method: 'post', contentType: 'application/json',
      payload: JSON.stringify({ref: 'main', inputs: {send_test_email: false}})});
    properties.setProperty('LAST_DISPATCH_MS', String(Date.now()));
    console.log('Reguläre Quellenprüfung auf main beauftragt.');
  } finally {
    lock.releaseLock();
  }
}
