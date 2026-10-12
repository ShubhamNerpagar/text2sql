from __future__ import annotations
from app.services.market_service import MarketService
from app.services.text_utils import normalize, phrase_in_text

class ValueIndexService:
    """Metadata-only literal/entity resolver. No raw fact rows are required."""
    def __init__(self): self.markets=MarketService()

    def entries(self,market:str)->list[dict]:
        ctx=self.markets.context(market); mappings=ctx.get('value_mappings',{}) or {}; out=[]
        for dimension,values in mappings.items():
            if not isinstance(values,dict): continue
            for canonical,spec in values.items():
                spec=spec or {}; label=spec.get('label',canonical)
                aliases={canonical,label}
                for a in spec.get('aliases',[]) or []: aliases.add(str(a))
                reps=spec.get('representations',{}) or {}
                for v in reps.values(): aliases.add(str(v))
                out.append({
                    'dimension':dimension,'canonical':canonical,'label':label,
                    'aliases':sorted(a for a in aliases if a),
                    'representations':reps,
                })
        return out

    def resolve(self,text:str,market:str)->list[dict]:
        found=[]
        for e in self.entries(market):
            matched=[]
            for alias in e['aliases']:
                if phrase_in_text(alias,text): matched.append(alias)
            # Avoid treating tiny internal codes such as AU as natural-language hits unless explicitly present as a token.
            if matched:
                confidence=.98 if any(normalize(x)==normalize(e['label']) for x in matched) else .92
                found.append({**e,'matched':matched,'confidence':confidence})
        # One canonical value per dimension/value pair.
        uniq={}
        for x in found: uniq[(x['dimension'],x['canonical'])]=x
        return list(uniq.values())
