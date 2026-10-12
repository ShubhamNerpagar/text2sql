from __future__ import annotations
import re
import unicodedata

STOPWORDS={
    'a','an','the','of','to','for','in','on','at','by','with','and','or','from','as','is','was','were','be','been','being',
    'what','which','who','how','show','give','list','tell','me','please','all','any','this','that','these','those','did','do',
    'de','du','des','la','le','les','un','une','dans','sur','pour','avec','et','ou','quel','quelle','quels','quelles','combien',
    'affiche','montre','donne','en','au','aux','par','est','sont','été','etre','être'
}

def normalize(text:str)->str:
    text=unicodedata.normalize('NFKD', text or '')
    text=''.join(c for c in text if not unicodedata.combining(c))
    return re.sub(r'[^a-z0-9]+',' ',text.lower()).strip()

def tokens(text:str,min_len:int=2)->list[str]:
    return [t for t in normalize(text).split() if len(t)>=min_len and t not in STOPWORDS]

def token_set(text:str,min_len:int=2)->set[str]:
    return set(tokens(text,min_len))

def phrase_in_text(phrase:str,text:str)->bool:
    p=normalize(phrase); t=normalize(text)
    if not p: return False
    return bool(re.search(r'(?<![a-z0-9])'+re.escape(p)+r'(?![a-z0-9])',t))

def similarity(a:str,b:str)->float:
    aa=token_set(a); bb=token_set(b)
    if not aa or not bb: return 0.0
    inter=len(aa & bb)
    if not inter: return 0.0
    # Dice coefficient favors compact business questions over long descriptions.
    return 2.0*inter/(len(aa)+len(bb))

def clamp(v:float,lo:float=0.0,hi:float=1.0)->float:
    return max(lo,min(hi,float(v)))
