"""
Hardcoded descriptions for official Claude Code plugins.

This module provides curated descriptions, usage instructions, and examples
for known official plugins from Anthropic.
"""

from typing import TypedDict, List, Optional


class PluginInfo(TypedDict, total=False):
    """Plugin information structure."""
    description: str
    usage: str
    examples: List[str]


# Mapping of plugin names to their descriptions
# Keys are the plugin name (without the @source suffix)
OFFICIAL_PLUGIN_DESCRIPTIONS: dict[str, PluginInfo] = {
    "document-skills": {
        "description": "Comprehensive document creation and manipulation toolkit. Supports creating, editing, and analyzing PDF, DOCX, XLSX, and PPTX files with full formatting support.",
        "usage": "Use slash commands like /pdf, /docx, /xlsx, /pptx to work with documents. The plugin provides tools for creating new documents, modifying existing ones, extracting content, and handling forms.",
        "examples": [
            "/pdf - Create or manipulate PDF documents",
            "/docx - Work with Word documents including tracked changes",
            "/xlsx - Create spreadsheets with formulas and formatting",
            "/pptx - Build presentations with layouts and speaker notes",
        ],
    },
    "context7": {
        "description": "Library documentation lookup tool that retrieves up-to-date documentation and code examples for any programming library or framework directly from Context7.",
        "usage": "When you need documentation for a library, Claude will automatically use Context7 to fetch current documentation. You can ask about any library's API, usage patterns, or code examples.",
        "examples": [
            "Ask about React hooks usage",
            "Get FastAPI endpoint documentation",
            "Look up Pandas DataFrame methods",
            "Find Next.js routing examples",
        ],
    },
    "frontend-design": {
        "description": "Create distinctive, production-grade frontend interfaces with high design quality. Generates creative, polished React components and UI designs.",
        "usage": "Use when building web components, pages, dashboards, or applications. The plugin helps create websites, landing pages, React components, and HTML/CSS layouts with professional styling.",
        "examples": [
            "Build a responsive landing page",
            "Create a dashboard with charts",
            "Design a form with validation",
            "Style a navigation component",
        ],
    },
    "example-skills": {
        "description": "Collection of example skills demonstrating various Claude Code capabilities including document creation, design, and workflow automation.",
        "usage": "Reference these as templates when creating custom skills or use them directly for common tasks like algorithmic art, brand guidelines, or MCP server building.",
        "examples": [
            "/algorithmic-art - Create generative art with p5.js",
            "/brand-guidelines - Apply Anthropic brand styling",
            "/mcp-builder - Guide for creating MCP servers",
            "/skill-creator - Create new custom skills",
        ],
    },
    "commit-commands": {
        "description": "Git workflow automation for committing, pushing, and creating pull requests with proper formatting and conventions.",
        "usage": "Use slash commands for streamlined git operations. The plugin handles commit message formatting, branch management, and PR creation.",
        "examples": [
            "/commit - Create a well-formatted git commit",
            "/commit-push-pr - Commit, push, and open a PR in one step",
            "/clean_gone - Clean up deleted remote branches",
        ],
    },
    "code-review": {
        "description": "Automated code review for pull requests. Analyzes code changes for bugs, security issues, and adherence to best practices.",
        "usage": "Use /code-review with a PR number or URL to get a comprehensive review of the changes including potential issues and improvement suggestions.",
        "examples": [
            "/code-review 123 - Review PR #123",
            "/code-review https://github.com/org/repo/pull/123",
        ],
    },
    "feature-dev": {
        "description": "Guided feature development with codebase understanding and architecture focus. Helps plan and implement new features systematically.",
        "usage": "Use /feature-dev to start a guided workflow for implementing new features. The plugin helps understand existing patterns and plan implementation steps.",
        "examples": [
            "/feature-dev - Start guided feature development",
            "Analyze codebase architecture before implementing",
            "Plan implementation with consideration for existing patterns",
        ],
    },
    "agent-sdk-dev": {
        "description": "Tools for building applications with the Claude Agent SDK. Helps create, configure, and verify Agent SDK applications.",
        "usage": "Use when building custom Claude agents. The plugin provides templates, verification, and best practices for both Python and TypeScript implementations.",
        "examples": [
            "/new-sdk-app - Create a new Agent SDK application",
            "Verify Agent SDK app configuration",
            "Follow SDK best practices and patterns",
        ],
    },
    "ralph-wiggum": {
        "description": "Loop and iteration technique for complex multi-step tasks. Named after the Simpsons character, this plugin helps manage iterative workflows.",
        "usage": "Use for tasks that require multiple iterations or continuous operation. Start a loop session and the plugin manages the iteration state.",
        "examples": [
            "/ralph-loop - Start an iterative loop session",
            "/cancel-ralph - Cancel an active loop",
            "/help - Get help on Ralph Wiggum techniques",
        ],
    },
    "canvas-design": {
        "description": "Create beautiful visual art and designs in PNG and PDF formats using design principles. Ideal for posters, artwork, and static visual pieces.",
        "usage": "Use when asked to create posters, artwork, designs, or other static visual pieces. The plugin applies design philosophy to create original visuals.",
        "examples": [
            "Create a poster design",
            "Generate visual artwork",
            "Design infographics",
        ],
    },
    "algorithmic-art": {
        "description": "Create algorithmic and generative art using p5.js with seeded randomness and interactive parameter exploration.",
        "usage": "Use for creating generative art, flow fields, particle systems, or any code-based artistic creation with controllable randomness.",
        "examples": [
            "Create a flow field visualization",
            "Generate particle system art",
            "Build interactive generative sketches",
        ],
    },
    "mcp-builder": {
        "description": "Guide for creating high-quality MCP (Model Context Protocol) servers. Helps build servers that enable LLMs to interact with external services.",
        "usage": "Use when building MCP servers to integrate external APIs or services. Supports both Python (FastMCP) and Node/TypeScript implementations.",
        "examples": [
            "Create a new MCP server for an API",
            "Design MCP tools for a service",
            "Follow MCP best practices",
        ],
    },
    "skill-creator": {
        "description": "Guide for creating effective custom skills that extend Claude's capabilities with specialized knowledge, workflows, or tool integrations.",
        "usage": "Use when you want to create or update a skill that adds new capabilities to Claude Code.",
        "examples": [
            "Create a new custom skill",
            "Update an existing skill",
            "Design skill workflows",
        ],
    },
    "internal-comms": {
        "description": "Resources for writing internal communications including status reports, leadership updates, newsletters, FAQs, and incident reports.",
        "usage": "Use when writing any internal communication. The plugin provides templates and formats for various communication types.",
        "examples": [
            "Write a status report",
            "Create a leadership update",
            "Draft an incident report",
            "Compose a project update",
        ],
    },
    "doc-coauthoring": {
        "description": "Structured workflow for co-authoring documentation, proposals, technical specs, and decision documents with iterative refinement.",
        "usage": "Use when writing documentation, proposals, or specs. The workflow helps transfer context, refine content, and verify readability.",
        "examples": [
            "Co-author technical documentation",
            "Write a design proposal",
            "Draft a decision document",
        ],
    },
    "webapp-testing": {
        "description": "Toolkit for interacting with and testing local web applications using Playwright. Supports UI verification, debugging, and screenshot capture.",
        "usage": "Use to test frontend functionality, debug UI behavior, capture browser screenshots, and view browser logs for local web applications.",
        "examples": [
            "Test a web application UI",
            "Debug frontend behavior",
            "Capture browser screenshots",
            "View browser console logs",
        ],
    },
}


def get_plugin_info(plugin_name: str) -> Optional[PluginInfo]:
    """
    Get detailed information for a known official plugin.

    Args:
        plugin_name: The plugin name (without @source suffix)

    Returns:
        PluginInfo dict if found, None otherwise
    """
    return OFFICIAL_PLUGIN_DESCRIPTIONS.get(plugin_name)


def get_all_known_plugins() -> List[str]:
    """
    Get list of all known official plugin names.

    Returns:
        List of plugin names
    """
    return list(OFFICIAL_PLUGIN_DESCRIPTIONS.keys())
