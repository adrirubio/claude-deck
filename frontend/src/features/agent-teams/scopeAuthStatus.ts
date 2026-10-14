import type { TeamGithubScope } from '@/types/agentTeams'

export function authStatus(scope: TeamGithubScope) {
  if (!scope.github_poll_token_configured) return {
    label: 'Polling token not set',
    help: 'Set github_token in backend/.env and restart Deck. The watcher uses this host token to poll GitHub; private repos cannot be polled through App settings alone.',
    warning: true,
  }
  if (!scope.github_auth_configured) return {
    label: 'GitHub App setup incomplete',
    help: 'Complete the GitHub App settings in backend/.env or remove partial App settings, then restart Deck. Deck selects a dispatch auth mode when eligible work is dispatched.',
    warning: true,
  }
  if (scope.github_auth_mode === 'unknown') return {
    label: 'Dispatch auth: not selected',
    help: 'The watcher can poll with the host token, but Deck selects a dispatch authentication mode only when eligible work is dispatched. A successful poll alone does not select the mode.',
    warning: false,
  }
  return {
    label: scope.github_auth_mode === 'app' ? 'Auth mode: GitHub App' : 'Auth mode: host token',
    help: scope.last_polled_at ? 'Deck has polled this repo. Check Activity for any later GitHub errors.' : 'Authentication mode selected; Deck has not completed a poll yet.',
    warning: false,
  }
}
