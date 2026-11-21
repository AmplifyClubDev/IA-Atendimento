#!/usr/bin/env python3
"""Cliente mínimo da API GraphQL do Railway (só biblioteca padrão).

Uso:
  railway_api.py projects
  railway_api.py project  --project ID
  railway_api.py deploys  --project ID --service ID [--env ID] [--limit 5]
  railway_api.py logs     --deployment ID [--build] [--limit 100] [--filter TEXTO]
  railway_api.py vars     --project ID --env ID [--service ID] [--show-values]
  railway_api.py redeploy --service ID --env ID --yes
  railway_api.py restart  --deployment ID --yes
  railway_api.py query    'GRAPHQL' ['{"var": 1}']

Token (o primeiro que existir):
  RAILWAY_API_TOKEN  -> conta/workspace (header Authorization: Bearer)
  RAILWAY_TOKEN      -> token de projeto (header Project-Access-Token)
  nenhum             -> envia um token "dummy" (no Claude Code na nuvem o proxy
                        troca pelo token real conectado à sessão)

IDs padrão podem vir de RAILWAY_PROJECT_ID, RAILWAY_ENVIRONMENT_ID e
RAILWAY_SERVICE_ID.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

ENDPOINT = os.environ.get("RAILWAY_API_URL", "https://backboard.railway.com/graphql/v2")


def headers() -> dict[str, str]:
    h = {"Content-Type": "application/json", "User-Agent": "claude-code-railway-plugin"}
    if os.environ.get("RAILWAY_API_TOKEN"):
        h["Authorization"] = f"Bearer {os.environ['RAILWAY_API_TOKEN']}"
    elif os.environ.get("RAILWAY_TOKEN"):
        h["Project-Access-Token"] = os.environ["RAILWAY_TOKEN"]
    else:
        h["Authorization"] = "Bearer dummy"
    return h


def gql(query: str, variables: dict | None = None) -> dict:
    body = json.dumps({"query": query, "variables": variables or {}}).encode()
    req = urllib.request.Request(ENDPOINT, data=body, headers=headers(), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.load(resp)
    except urllib.error.HTTPError as exc:
        sys.exit(f"HTTP {exc.code}: {exc.read().decode(errors='replace')[:500]}")
    if payload.get("errors"):
        msgs = "; ".join(e.get("message", "?") for e in payload["errors"])
        sys.exit(f"Erro do Railway: {msgs}")
    return payload["data"]


def edges(conn: dict | None) -> list[dict]:
    return [e["node"] for e in (conn or {}).get("edges", [])]


def need(value: str | None, name: str) -> str:
    if not value:
        sys.exit(f"Falta --{name} (ou a variável RAILWAY_{name.upper()}_ID).")
    return value


def out(data) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False))


# ---------------------------------------------------------------- comandos

def cmd_projects(a):
    data = gql("""{ projects { edges { node { id name
        environments { edges { node { id name } } }
        services { edges { node { id name } } } } } } }""")
    out([
        {"id": p["id"], "name": p["name"],
         "environments": edges(p["environments"]), "services": edges(p["services"])}
        for p in edges(data["projects"])
    ])


def cmd_project(a):
    pid = need(a.project, "project")
    data = gql("""query($id: String!) { project(id: $id) { id name
        environments { edges { node { id name } } }
        services { edges { node { id name
          deployments(first: 1) { edges { node { id status createdAt staticUrl } } } } } } } }""",
               {"id": pid})
    p = data["project"]
    out({
        "id": p["id"], "name": p["name"],
        "environments": edges(p["environments"]),
        "services": [
            {"id": s["id"], "name": s["name"],
             "ultimo_deploy": (edges(s.get("deployments")) or [None])[0]}
            for s in edges(p["services"])
        ],
    })


def cmd_deploys(a):
    inp = {"projectId": need(a.project, "project"), "serviceId": need(a.service, "service")}
    if a.env:
        inp["environmentId"] = a.env
    data = gql("""query($input: DeploymentListInput!, $n: Int) {
        deployments(input: $input, first: $n) { edges { node {
          id status createdAt staticUrl meta } } } }""", {"input": inp, "n": a.limit})
    rows = edges(data["deployments"])
    for r in rows:  # meta é grande; mantém só o que ajuda a identificar o deploy
        meta = r.pop("meta", None) or {}
        r["commit"] = {k: meta.get(k) for k in ("commitHash", "commitMessage", "branch") if meta.get(k)}
    out(rows)


def cmd_logs(a):
    field = "buildLogs" if a.build else "deploymentLogs"
    args = "deploymentId: $id, limit: $n" + (", filter: $f" if a.filter else "")
    decl = "$id: String!, $n: Int" + (", $f: String" if a.filter else "")
    q = f"query({decl}) {{ {field}({args}) {{ timestamp severity message }} }}"
    vars_ = {"id": a.deployment, "n": a.limit}
    if a.filter:
        vars_["f"] = a.filter
    for line in gql(q, vars_)[field]:
        print(f"{line.get('timestamp', '')} [{line.get('severity') or '-'}] {line.get('message', '')}")


def cmd_vars(a):
    v = {"p": need(a.project, "project"), "e": need(a.env, "env")}
    decl, args = "$p: String!, $e: String!", "projectId: $p, environmentId: $e"
    if a.service:
        v["s"] = a.service
        decl += ", $s: String"
        args += ", serviceId: $s"
    data = gql(f"query({decl}) {{ variables({args}) }}", v)["variables"]
    if a.show_values:
        out(data)
    else:  # por padrão só nomes: valores costumam ser segredos
        out({k: f"<{len(str(val))} caracteres>" for k, val in sorted(data.items())})


def cmd_redeploy(a):
    if not a.yes:
        sys.exit("Redeploy muda produção. Rode de novo com --yes depois de confirmar.")
    gql("""mutation($s: String!, $e: String!) {
        serviceInstanceRedeploy(serviceId: $s, environmentId: $e) }""",
        {"s": need(a.service, "service"), "e": need(a.env, "env")})
    print("Redeploy pedido. Acompanhe com: deploys --project ... --service ...")


def cmd_restart(a):
    if not a.yes:
        sys.exit("Restart muda produção. Rode de novo com --yes depois de confirmar.")
    gql("mutation($id: String!) { deploymentRestart(id: $id) }", {"id": a.deployment})
    print("Restart pedido.")


def cmd_query(a):
    out(gql(a.graphql, json.loads(a.variables) if a.variables else None))


def main() -> None:
    env = os.environ.get
    ap = argparse.ArgumentParser(description="API do Railway para o Claude Code")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, fn, *opts):
        p = sub.add_parser(name)
        p.set_defaults(fn=fn)
        for o in opts:
            o(p)
        return p

    project = lambda p: p.add_argument("--project", default=env("RAILWAY_PROJECT_ID"))
    service = lambda p: p.add_argument("--service", default=env("RAILWAY_SERVICE_ID"))
    envarg = lambda p: p.add_argument("--env", default=env("RAILWAY_ENVIRONMENT_ID"))
    yes = lambda p: p.add_argument("--yes", action="store_true")
    deployment = lambda p: p.add_argument("--deployment", required=True)

    add("projects", cmd_projects)
    add("project", cmd_project, project)
    add("deploys", cmd_deploys, project, service, envarg,
        lambda p: p.add_argument("--limit", type=int, default=5))
    add("logs", cmd_logs, deployment,
        lambda p: p.add_argument("--build", action="store_true"),
        lambda p: p.add_argument("--limit", type=int, default=100),
        lambda p: p.add_argument("--filter"))
    add("vars", cmd_vars, project, envarg, service,
        lambda p: p.add_argument("--show-values", action="store_true"))
    add("redeploy", cmd_redeploy, service, envarg, yes)
    add("restart", cmd_restart, deployment, yes)
    add("query", cmd_query,
        lambda p: p.add_argument("graphql"),
        lambda p: p.add_argument("variables", nargs="?"))

    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
