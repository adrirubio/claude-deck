import { defineConfig } from 'vitepress'

export default defineConfig({
  title: 'Claude Deck',
  description: 'Documentation for Claude Deck — Web Dashboard for Claude Code',
  appearance: 'force-dark',
  base: '/docs/',
  head: [
    ['link', { rel: 'icon', href: '/docs/favicon.ico' }],
  ],

  themeConfig: {
    logo: '/logo-dark.png',
    siteTitle: 'Claude Deck',

    nav: [
      { text: 'Guide', link: '/guide/' },
      { text: 'Features', link: '/features/dashboard' },
      { text: 'API Reference', link: '/api/' },
      {
        text: 'v1.1.0',
        link: 'https://github.com/adrirubio/claude-deck/blob/master/CHANGELOG.md',
      },
    ],

    sidebar: {
      '/guide/': [
        {
          text: 'Guide',
          items: [
            { text: 'Introduction', link: '/guide/' },
            { text: 'Installation', link: '/guide/installation' },
            { text: 'Quick Start', link: '/guide/quick-start' },
            { text: 'Architecture', link: '/guide/architecture' },
            { text: 'Contributing', link: '/guide/contributing' },
          ],
        },
      ],
      '/features/': [
        {
          text: 'Features',
          items: [
            { text: 'Dashboard', link: '/features/dashboard' },
            { text: 'Config', link: '/features/config' },
            { text: 'MCP Servers', link: '/features/mcp-servers' },
            { text: 'Commands', link: '/features/commands' },
            { text: 'Plugins', link: '/features/plugins' },
            { text: 'Hooks', link: '/features/hooks' },
            { text: 'Permissions', link: '/features/permissions' },
            { text: 'Agents & Skills', link: '/features/agents-skills' },
            { text: 'Memory', link: '/features/memory' },
            { text: 'Output Styles', link: '/features/output-styles' },
            { text: 'Status Line', link: '/features/statusline' },
            { text: 'Sessions', link: '/features/sessions' },
            { text: 'CC Bridge', link: '/features/cc-bridge' },
            { text: 'Usage Tracking', link: '/features/usage' },
            { text: 'Backup & Restore', link: '/features/backup' },
          ],
        },
      ],
      '/api/': [
        {
          text: 'API Reference',
          items: [
            { text: 'Overview', link: '/api/' },
            { text: 'Config', link: '/api/config' },
            { text: 'MCP Servers', link: '/api/mcp' },
            { text: 'Commands', link: '/api/commands' },
            { text: 'Plugins', link: '/api/plugins' },
            { text: 'Hooks', link: '/api/hooks' },
            { text: 'Permissions', link: '/api/permissions' },
            { text: 'Agents', link: '/api/agents' },
            { text: 'Sessions', link: '/api/sessions' },
            { text: 'Context', link: '/api/context' },
            { text: 'Plans', link: '/api/plans' },
            { text: 'Output Styles', link: '/api/output-styles' },
            { text: 'Status Line', link: '/api/statusline' },
            { text: 'CC Bridge', link: '/api/cc-bridge' },
            { text: 'Usage', link: '/api/usage' },
            { text: 'Memory', link: '/api/memory' },
            { text: 'Backup', link: '/api/backup' },
          ],
        },
      ],
    },

    socialLinks: [
      { icon: 'github', link: 'https://github.com/adrirubio/claude-deck' },
    ],

    search: {
      provider: 'local',
    },

    editLink: {
      pattern: 'https://github.com/adrirubio/claude-deck/edit/master/docs/:path',
      text: 'Edit this page on GitHub',
    },

    footer: {
      message: 'Released under the MIT License.',
      copyright: 'Copyright © 2026 Claude Deck Contributors',
    },
  },
})
