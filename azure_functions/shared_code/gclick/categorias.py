ALLOWED_CATEGORIES = [
    "Obrigacao",
    "Solicitacao",
    "Cobranca",
    "CertificadoDigital",
    "Agendamento"
]

def escolher_categoria(preferida=None):
    if preferida and preferida in ALLOWED_CATEGORIES:
        return preferida
    return "Obrigacao"
