import { NavLink } from "react-router-dom";
import { cn } from "@/lib/utils";
import { ProjectSwitcher } from "@/features/projects/ProjectSwitcher";
import { useSidebar } from "@/contexts/SidebarContext";
import { useProviderContext } from "@/contexts/ProviderContext";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type {
  AgentProviderCapabilities,
  AgentProviderId,
  AgentProviderStatus,
} from "@/types/providers";
import {
  LayoutDashboard,
  Settings,
  Server,
  Terminal,
  Package,
  Webhook,
  Shield,
  Bot,
  Sparkles,
  Brain,
  Paintbrush,
  Activity,
  MessageSquare,
  BarChart3,
  FolderOpen,
  Archive,
  Gauge,
  ClipboardList,
  MonitorPlay,
  Mail,
  UsersRound,
  PanelLeftClose,
  PanelLeftOpen,
  type LucideIcon,
} from "lucide-react";

type NavItem = {
  name: string;
  href: string;
  icon: LucideIcon;
  capability?: keyof AgentProviderCapabilities;
};

type NavGroup = {
  name: string;
  items: NavItem[];
};

const commonNavigation: NavGroup[] = [
  {
    name: "Core",
    items: [
      { name: "Dashboard", href: "/", icon: LayoutDashboard },
      { name: "Projects", href: "/projects", icon: FolderOpen },
      {
        name: "Agent Bridge",
        href: "/agent-bridge",
        icon: MonitorPlay,
        capability: "sessions",
      },
    ],
  },
  {
    name: "Operations",
    items: [
      { name: "Agent Mail", href: "/agent-mail", icon: Mail },
      { name: "Agent Teams", href: "/agent-teams", icon: UsersRound },
      {
        name: "Plans",
        href: "/plans",
        icon: ClipboardList,
        capability: "plans",
      },
      { name: "Backup", href: "/backup", icon: Archive, capability: "backup" },
    ],
  },
];

const providerNavigation: Record<AgentProviderId, NavGroup[]> = {
  "claude-code": [
    {
      name: "Claude Code",
      items: [
        {
          name: "Config",
          href: "/config",
          icon: Settings,
          capability: "config",
        },
        {
          name: "Sessions",
          href: "/sessions",
          icon: MessageSquare,
          capability: "sessions",
        },
        { name: "MCP Servers", href: "/mcp", icon: Server, capability: "mcp" },
        {
          name: "Plugins",
          href: "/plugins",
          icon: Package,
          capability: "plugins",
        },
        {
          name: "Permissions / Trust",
          href: "/permissions",
          icon: Shield,
          capability: "permissions",
        },
      ],
    },
    {
      name: "Claude Tools",
      items: [
        {
          name: "Commands",
          href: "/commands",
          icon: Terminal,
          capability: "commands",
        },
        { name: "Hooks", href: "/hooks", icon: Webhook, capability: "hooks" },
        { name: "Agents", href: "/agents", icon: Bot, capability: "agents" },
        {
          name: "Skills",
          href: "/skills",
          icon: Sparkles,
          capability: "skills",
        },
        { name: "Memory", href: "/memory", icon: Brain, capability: "memory" },
        {
          name: "Output Styles",
          href: "/output-styles",
          icon: Paintbrush,
          capability: "output_styles",
        },
        {
          name: "Status Line",
          href: "/statusline",
          icon: Activity,
          capability: "statusline",
        },
      ],
    },
    {
      name: "Claude Metrics",
      items: [
        {
          name: "Context",
          href: "/context",
          icon: Gauge,
          capability: "context",
        },
        { name: "Usage", href: "/usage", icon: BarChart3, capability: "usage" },
      ],
    },
  ],
  "codex-cli": [
    {
      name: "Codex",
      items: [
        {
          name: "Config",
          href: "/config",
          icon: Settings,
          capability: "config",
        },
        { name: "MCP Servers", href: "/mcp", icon: Server, capability: "mcp" },
        {
          name: "Plugins",
          href: "/plugins",
          icon: Package,
          capability: "plugins",
        },
      ],
    },
  ],
};

function getNavigation(providerId: AgentProviderId): NavGroup[] {
  return [...commonNavigation, ...(providerNavigation[providerId] ?? [])];
}

const visibleCapabilityStates = new Set([
  "supported",
  "read_only",
  "write_capable",
]);

function supportsProvider(item: NavItem, provider: AgentProviderStatus | null) {
  if (!item.capability || !provider) return true;
  const detail = provider.capability_matrix?.[item.capability];
  if (detail) return visibleCapabilityStates.has(detail.state);
  return Boolean(provider.capabilities?.[item.capability]);
}

function NavGroupSection({
  group,
  collapsed,
  selectedProvider,
}: {
  group: NavGroup;
  collapsed: boolean;
  selectedProvider: AgentProviderStatus | null;
}) {
  const visibleItems = group.items.filter((item) =>
    supportsProvider(item, selectedProvider),
  );
  if (visibleItems.length === 0) return null;

  return (
    <div className="space-y-1">
      {!collapsed && (
        <p className="px-3 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
          {group.name}
        </p>
      )}
      {visibleItems.map((item) => (
        <NavLink
          key={item.href}
          to={item.href}
          end={item.href === "/"}
          title={collapsed ? item.name : undefined}
          className={({ isActive }) =>
            cn(
              "flex items-center rounded-md text-sm font-medium transition-colors",
              collapsed ? "justify-center p-2" : "gap-2 px-3 py-2",
              isActive
                ? "bg-primary text-primary-foreground"
                : "text-foreground hover:bg-accent hover:text-accent-foreground",
            )
          }
        >
          <item.icon className="h-4 w-4 shrink-0" />
          {!collapsed && item.name}
        </NavLink>
      ))}
    </div>
  );
}

export function Sidebar() {
  const { collapsed, setCollapsed } = useSidebar();
  const {
    providers,
    selectedProviderId,
    selectedProvider,
    setSelectedProviderId,
  } = useProviderContext();
  const visibleGroups = getNavigation(selectedProviderId);

  return (
    <aside
      className={cn(
        "border-r bg-background transition-all duration-200 flex flex-col",
        collapsed ? "w-14" : "w-64",
      )}
    >
      {!collapsed && (
        <div className="py-4 border-b space-y-3">
          <ProjectSwitcher />
          <div className="px-4 space-y-1.5">
            <p className="text-xs font-medium text-muted-foreground">
              Agent Provider
            </p>
            <Select
              value={selectedProviderId}
              onValueChange={(value) =>
                setSelectedProviderId(value as AgentProviderId)
              }
            >
              <SelectTrigger className="h-9">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {providers.map((provider) => (
                  <SelectItem key={provider.id} value={provider.id}>
                    {provider.display_name}
                    {!provider.installed ? " (missing)" : ""}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
      )}
      <nav
        className={cn(
          "flex flex-col flex-1 overflow-y-auto",
          collapsed ? "gap-1 p-2" : "gap-4 p-4",
        )}
      >
        {visibleGroups.map((group) => (
          <NavGroupSection
            key={group.name}
            group={group}
            collapsed={collapsed}
            selectedProvider={selectedProvider}
          />
        ))}
      </nav>
      <button
        onClick={() => setCollapsed(!collapsed)}
        className="flex items-center justify-center p-3 border-t text-muted-foreground hover:text-foreground transition-colors"
        title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
      >
        {collapsed ? (
          <PanelLeftOpen className="h-4 w-4" />
        ) : (
          <PanelLeftClose className="h-4 w-4" />
        )}
      </button>
    </aside>
  );
}
