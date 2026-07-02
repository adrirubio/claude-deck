# Agents API

Manage agents and skills.

## Agent Endpoints

### List Agents

```http
GET /api/v1/agents?project_path={path}
```

### Get Agent

```http
GET /api/v1/agents/{scope}/{name}?project_path={path}
```

### Create Agent

```http
POST /api/v1/agents?project_path={path}
```

```json
{
  "name": "reviewer",
  "scope": "user",
  "description": "Code review specialist",
  "tools": ["Read", "Grep", "Glob"],
  "disallowed_tools": ["Write", "Bash"],
  "model": "claude-sonnet-5",
  "permission_mode": "default",
  "skills": ["code-review"],
  "memory": "user",
  "prompt": "You are a code review specialist..."
}
```

### Update Agent

```http
PUT /api/v1/agents/{scope}/{name}?project_path={path}
```

### Delete Agent

```http
DELETE /api/v1/agents/{scope}/{name}?project_path={path}
```

## Skill Endpoints

### List Skills

```http
GET /api/v1/agents/skills?project_path={path}
```

### Get Skill

```http
GET /api/v1/agents/skills/{location}/{name}?project_path={path}&include_deps={bool}
```

### Check Dependencies

```http
GET /api/v1/agents/skills/{location}/{name}/dependencies?project_path={path}
```

### Install Dependencies

```http
POST /api/v1/agents/skills/{location}/{name}/install?project_path={path}
```

### List Skill Files

```http
GET /api/v1/agents/skills/{location}/{name}/files?project_path={path}
```

### Search Registry

```http
GET /api/v1/agents/skills/registry?query={q}&limit={n}
```

### Install from Registry

```http
POST /api/v1/agents/skills/registry/install?project_path={path}
```

```json
{
  "source": "https://skills.sh/owner/skill",
  "skill_names": ["skill-name"],
  "global_install": true
}
```
