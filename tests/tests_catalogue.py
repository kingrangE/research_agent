import relations


def catalogue_for_research():
    return {p["code"]: {"code": p["code"], "name": p["label"], "country": "KR" if p["code"][0].isdigit() else "US",
                        "market": "KRX" if p["code"][0].isdigit() else "NASDAQ/NYSE", "products": p["activity"], "industry": "AI"}
            for p in relations.KNOWLEDGE["profiles"]}
