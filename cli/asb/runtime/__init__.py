"""cli/asb/runtime/ — fronteira tipada de descoberta e execucao de sandboxes.

Pacote NOVO (Tarefa 3). Nao confundir com `cli/asb/runtime_check.py`
(sonda executada DENTRO do container) nem com o `runtime_dir` que
`lifecycle.ensure_runtime` instala no host: sao conceitos ja existentes e
nenhum deles muda de lugar aqui.
"""
from __future__ import annotations
