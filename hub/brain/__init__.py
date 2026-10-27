"""Le « brain » (lot 7) : passerelle MCP et assistant local, sur le Mac.

Il ne voit le hub que par son API et un jeton à portées limitées (« brain » pour le modèle
local : lecture et propositions ; « agrégats » pour un client externe comme Claude : des totaux,
jamais une écriture). Il n'importe aucun domaine : les outils viennent du hub, domaine par
domaine, et s'y exécutent. Le modèle tourne en natif sur le Mac (Ollama, ou tout serveur qui
parle l'API compatible OpenAI, comme `mlx_lm.server`).
"""
