"""SQL Agent: consultas en lenguaje natural sobre la BD de negocio.

Grafo LangGraph independiente de los agentes ReAct de `src/agents/` (su
topología es un loop de autocorrección SQL, no razonar-tool-observar). Ver
`docs/arquitectura.md` §6.5 y `src/sql_agent/graph.py`.
"""
