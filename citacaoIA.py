"""
CitacaoIA -- Gestor Inteligente de Citacoes Cientificas Vancouver
Versao: 2.0
Uso: streamlit run citacaoIA.py
"""

import re, json, time, os
from datetime import datetime
from io import BytesIO

import streamlit as st
import requests

# ── PAGE CONFIG ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="CitacaoIA . Vancouver",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
:root {--primary:#1e3a5f;--accent:#2e7ddb;--bg:#f4f7fb;}
.stApp{background:var(--bg);}
.cia-header{background:linear-gradient(135deg,#1e3a5f,#2e7ddb);color:white;
  padding:1.4rem 2rem;border-radius:12px;margin-bottom:1.5rem;
  box-shadow:0 4px 18px rgba(30,58,95,.25);}
.cia-header h1{color:white;margin:0;font-size:2rem;}
.cia-header p{color:rgba(255,255,255,.82);margin:.3rem 0 0;font-size:.95rem;}
.pill-changed{background:#fff3cd;color:#7a4f00;border-radius:20px;
  padding:2px 10px;font-size:.78rem;font-weight:600;}
.pill-ok{background:#d4edda;color:#155724;border-radius:20px;
  padding:2px 10px;font-size:.78rem;font-weight:600;}
.ref-box{background:#f8f9fc;border-left:4px solid #2e7ddb;border-radius:0 8px 8px 0;
  padding:.7rem 1rem;font-size:.88rem;font-family:Georgia,serif;margin:.4rem 0;}
.art-card{background:white;border:1.5px solid #d0daea;border-radius:10px;
  padding:1rem 1.2rem;margin:.5rem 0;transition:border-color .2s;}
.art-card:hover{border-color:#2e7ddb;}
.art-title{font-size:1rem;font-weight:700;color:#1e3a5f;margin:0 0 .3rem;}
.art-meta{font-size:.82rem;color:#555;margin:.2rem 0;}
.step-badge{display:inline-block;background:#2e7ddb;color:white;border-radius:50%;
  width:24px;height:24px;line-height:24px;text-align:center;
  font-size:.8rem;font-weight:700;margin-right:6px;}
</style>
""", unsafe_allow_html=True)

# ── CONSTANTS ─────────────────────────────────────────────────────────────────
PUBMED_BASE   = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
SEMANTIC_BASE = "https://api.semanticscholar.org/graph/v1/paper/search"
CROSSREF_BASE = "https://api.crossref.org/works/"
MAX_SEARCHES  = 6
BIBLIOTECA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "citacaoIA_biblioteca.json")

# =============================================================================
# SUPABASE HELPER  (usado quando configurado; cai para JSON local caso contrario)
# =============================================================================

def _supa_cfg():
    """Return (url, headers) or (None, None) if Supabase not configured."""
    try:
        url = st.secrets["supabase"]["url"].rstrip("/")
        key = st.secrets["supabase"]["key"]
        return url, {"apikey": key, "Authorization": f"Bearer {key}",
                     "Content-Type": "application/json", "Prefer": "return=representation"}
    except Exception:
        return None, None

def _supa_available() -> bool:
    url, _ = _supa_cfg()
    return url is not None

# =============================================================================
# BIBLIOTECA  (Supabase quando disponivel, JSON local como fallback)
# =============================================================================

def load_library() -> list:
    url, hdrs = _supa_cfg()
    if url:
        try:
            r = requests.get(f"{url}/rest/v1/citacaoIA_biblioteca",
                             params={"select":"*","order":"added_date.desc"},
                             headers=hdrs, timeout=10)
            if r.status_code == 200:
                rows = r.json()
                return [row["article_data"] for row in rows if row.get("article_data")]
        except Exception:
            pass
    # fallback: JSON local
    if os.path.exists(BIBLIOTECA_FILE):
        try:
            with open(BIBLIOTECA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_library(library: list) -> bool:
    """Save to JSON (local only). Cloud saves are done incrementally via Supabase."""
    try:
        folder = os.path.dirname(BIBLIOTECA_FILE)
        if folder and not os.path.exists(folder):
            os.makedirs(folder, exist_ok=True)
        with open(BIBLIOTECA_FILE, "w", encoding="utf-8") as f:
            json.dump(library, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        return False

def _supa_upsert(article: dict):
    """Insert or update a single article in Supabase."""
    url, hdrs = _supa_cfg()
    if not url:
        return
    doi   = article.get("doi","").lower().strip()
    title = article.get("title","").lower()[:60]
    # Check if exists by DOI or title
    try:
        params = {"select":"id,article_data"}
        if doi:
            params["article_data->>doi"] = f"eq.{doi}"
        r = requests.get(f"{url}/rest/v1/citacaoIA_biblioteca",
                         params=params, headers=hdrs, timeout=8)
        existing = r.json() if r.status_code == 200 else []
        if not existing and title:
            r2 = requests.get(f"{url}/rest/v1/citacaoIA_biblioteca",
                              params={"select":"id","article_data->>title": f"ilike.{article.get('title','')[:60]}%"},
                              headers=hdrs, timeout=8)
            existing = r2.json() if r2.status_code == 200 else []
        if existing:
            row_id = existing[0]["id"]
            requests.patch(f"{url}/rest/v1/citacaoIA_biblioteca?id=eq.{row_id}",
                           json={"article_data": article}, headers=hdrs, timeout=8)
        else:
            article["added_date"] = article.get("added_date", datetime.now().isoformat())
            requests.post(f"{url}/rest/v1/citacaoIA_biblioteca",
                          json={"article_data": article}, headers=hdrs, timeout=8)
    except Exception:
        pass

def _supa_delete(article: dict):
    """Delete a single article from Supabase by DOI or title."""
    url, hdrs = _supa_cfg()
    if not url:
        return
    doi = article.get("doi","").lower().strip()
    try:
        if doi:
            requests.delete(f"{url}/rest/v1/citacaoIA_biblioteca",
                            params={"article_data->>doi": f"eq.{doi}"},
                            headers=hdrs, timeout=8)
        else:
            title = article.get("title","")[:60]
            requests.delete(f"{url}/rest/v1/citacaoIA_biblioteca",
                            params={"article_data->>title": f"ilike.{title}%"},
                            headers=hdrs, timeout=8)
    except Exception:
        pass

def add_to_library(article: dict) -> tuple:
    """Add or update article. Returns (library, is_new)."""
    lib = load_library()
    doi = article.get("doi","").lower().strip()
    is_new = True
    for i, a in enumerate(lib):
        if doi and a.get("doi","").lower().strip() == doi:
            lib[i] = {**a, **article, "added_date": a.get("added_date", datetime.now().isoformat())}
            is_new = False
            break
        if a.get("title","").lower()[:60] == article.get("title","").lower()[:60]:
            lib[i] = {**a, **article, "added_date": a.get("added_date", datetime.now().isoformat())}
            is_new = False
            break
    if is_new:
        article["added_date"] = datetime.now().isoformat()
        lib.insert(0, article)
    save_library(lib)
    _supa_upsert(article if not is_new else lib[0])
    return lib, is_new

def delete_from_library(index: int) -> list:
    lib = load_library()
    if 0 <= index < len(lib):
        art = lib[index]
        lib.pop(index)
        save_library(lib)
        _supa_delete(art)
    return lib

def search_library(query: str) -> list:
    lib = load_library()
    if not query.strip():
        return lib
    q = query.lower()
    return [a for a in lib if
            q in a.get("title","").lower() or
            q in " ".join(a.get("authors",[])).lower() or
            q in a.get("journal","").lower() or
            q in a.get("year","").lower() or
            q in a.get("doi","").lower() or
            q in a.get("abstract","").lower()]

# =============================================================================
# DOI LOOKUP (CrossRef)
# =============================================================================

def lookup_doi(doi: str) -> dict | None:
    doi = doi.strip().lstrip("https://doi.org/").lstrip("http://doi.org/").lstrip("doi:")
    try:
        r = requests.get(CROSSREF_BASE + doi, timeout=12,
                         headers={"User-Agent": "CitacaoIA/2.0 mailto:research@borghi.med.br"})
        if r.status_code != 200:
            return None
        data = r.json().get("message", {})

        # Authors
        authors = []
        for a in data.get("author", []):
            family = a.get("family", "")
            given  = a.get("given", "")
            if family:
                initials = "".join(w[0] for w in given.split() if w) if given else ""
                authors.append(f"{family} {initials}".strip())

        # Journal
        journal = ""
        containers = data.get("container-title", [])
        if containers:
            journal = containers[0]

        # Year
        year = ""
        dp = data.get("published", data.get("published-print", data.get("published-online", {})))
        parts = dp.get("date-parts", [[""]])[0]
        if parts:
            year = str(parts[0])

        # Title
        titles = data.get("title", [""])
        title = titles[0] if titles else ""

        # Pages
        pages = data.get("page", "")

        return {
            "doi":      doi,
            "title":    title,
            "authors":  authors,
            "journal":  journal,
            "year":     year,
            "volume":   str(data.get("volume", "")),
            "issue":    str(data.get("issue", "")),
            "pages":    pages,
            "abstract": data.get("abstract", ""),
            "_source":  "CrossRef/DOI",
        }
    except Exception as e:
        return None

# =============================================================================
# WEB SEARCH — PubMed, LILACS, Embase (via Europe PMC), Semantic Scholar,
#              OpenAlex (busca cinzenta / literatura expandida)
# =============================================================================

def search_pubmed(query: str, max_results: int = 3) -> list:
    """Search PubMed via NCBI eutils (free API, no key needed)."""
    try:
        r = requests.get(PUBMED_BASE + "esearch.fcgi",
            params={"db":"pubmed","term":query,"retmax":max_results,"retmode":"json"}, timeout=10)
        pmids = r.json().get("esearchresult", {}).get("idlist", [])
        if not pmids:
            return []
        r2 = requests.get(PUBMED_BASE + "esummary.fcgi",
            params={"db":"pubmed","id":",".join(pmids),"retmode":"json"}, timeout=10)
        data = r2.json().get("result", {})
        articles = []
        for pmid in pmids:
            item = data.get(pmid, {})
            if not item or pmid == "uids":
                continue
            authors = [a.get("name","") for a in item.get("authors",[])]
            articles.append({
                "pmid": pmid, "title": item.get("title","").rstrip("."),
                "authors": authors, "journal": item.get("source",""),
                "year": item.get("pubdate","")[:4], "volume": item.get("volume",""),
                "issue": item.get("issue",""), "pages": item.get("pages",""),
                "doi": item.get("elocationid","").replace("doi: ",""), "_source": "PubMed",
            })
        return articles
    except Exception:
        return []


def search_europe_pmc(query: str, max_results: int = 3,
                      source_filter: str = "") -> list:
    """Search Europe PMC — covers PubMed Central, EMBASE subset, WHO IRIS, preprints.
    source_filter: '' = all, 'MED' = MEDLINE, 'PPR' = preprints (busca cinzenta)."""
    try:
        params = {
            "query": query + (f" SOURCE:{source_filter}" if source_filter else ""),
            "resultType": "core",
            "pageSize": max_results,
            "format": "json",
        }
        r = requests.get("https://www.ebi.ac.uk/europepmc/webservices/rest/search",
                         params=params, timeout=12)
        results = r.json().get("resultList", {}).get("result", [])
        articles = []
        for item in results:
            authors_raw = item.get("authorList", {}).get("author", [])
            if isinstance(authors_raw, list):
                authors = [f"{a.get('lastName','')} {a.get('initials','')}" for a in authors_raw]
            else:
                authors = [item.get("authorString","")]
            articles.append({
                "title":   item.get("title","").rstrip("."),
                "authors": authors,
                "journal": item.get("journalTitle",""),
                "year":    str(item.get("pubYear","")),
                "volume":  item.get("journalVolume",""),
                "issue":   item.get("issue",""),
                "pages":   item.get("pageInfo",""),
                "doi":     item.get("doi",""),
                "pmid":    item.get("pmid",""),
                "_source": f"Europe PMC{'/Preprint' if source_filter=='PPR' else ''}",
            })
        return articles
    except Exception:
        return []


def search_lilacs(query: str, max_results: int = 3) -> list:
    """Search LILACS via the free BVS/BIREME iAHx Solr endpoint (no auth required)."""
    articles = []
    # Strategy 1 — BVS iAHx Solr (free, JSON output)
    try:
        r = requests.get(
            "https://pesquisa.bvsalud.org/portal/api/",
            params={
                "q":    query,
                "site": "portal",
                "op":   "search",
                "lang": "pt",
                "fmt":  "json",
                "count": max_results,
            },
            timeout=12,
        )
        if r.status_code == 200:
            data = r.json()
            docs = (data.get("hits", {}).get("hits", []) or
                    data.get("documents", []) or
                    data.get("results", []))
            for doc in docs[:max_results]:
                src = doc.get("_source", doc)
                ti  = src.get("ti", src.get("title", ""))
                if isinstance(ti, dict):
                    ti = next(iter(ti.values()), "") if ti else ""
                if not str(ti).strip():
                    continue
                au = src.get("au", src.get("authors", []))
                if isinstance(au, str):
                    au = [au]
                articles.append({
                    "title":   str(ti).rstrip("."),
                    "authors": au,
                    "journal": src.get("ta", src.get("journal", "")),
                    "year":    str(src.get("dp", src.get("year", "")))[:4],
                    "volume":  src.get("vi", ""),
                    "issue":   src.get("ip", ""),
                    "pages":   src.get("pg", ""),
                    "doi":     src.get("doi", ""),
                    "_source": "LILACS/BVS",
                })
    except Exception:
        pass

    # Strategy 2 — Europe PMC with LILACS filter (free, covers Latin American journals)
    if not articles:
        try:
            r = requests.get(
                "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
                params={
                    "query":      query + " (JOURNAL_ISSN:\"LILACS\" OR SRC:AGR OR SRC:PAT)",
                    "resultType": "core",
                    "pageSize":   max_results,
                    "format":     "json",
                },
                timeout=12,
            )
            results = r.json().get("resultList", {}).get("result", [])
            for item in results:
                authors_raw = item.get("authorList", {}).get("author", [])
                if isinstance(authors_raw, list):
                    authors = [f"{a.get('lastName','')} {a.get('initials','')}" for a in authors_raw]
                else:
                    authors = [item.get("authorString", "")]
                articles.append({
                    "title":   item.get("title", "").rstrip("."),
                    "authors": authors,
                    "journal": item.get("journalTitle", ""),
                    "year":    str(item.get("pubYear", "")),
                    "volume":  item.get("journalVolume", ""),
                    "issue":   item.get("issue", ""),
                    "pages":   item.get("pageInfo", ""),
                    "doi":     item.get("doi", ""),
                    "pmid":    item.get("pmid", ""),
                    "_source": "LILACS/Europe PMC",
                })
        except Exception:
            pass

    return articles


def search_openalex(query: str, max_results: int = 3) -> list:
    """Search OpenAlex — open scholarly graph with 250M+ works (busca cinzenta ampliada)."""
    try:
        r = requests.get(
            "https://api.openalex.org/works",
            params={
                "search": query,
                "per_page": max_results,
                "select": "title,authorships,publication_year,primary_location,doi,biblio",
                "mailto": "research@borghi.med.br",
            },
            timeout=12,
        )
        items = r.json().get("results", [])
        articles = []
        for item in items:
            authors = [
                a.get("author", {}).get("display_name", "")
                for a in item.get("authorships", [])
            ]
            loc    = item.get("primary_location") or {}
            source = (loc.get("source") or {}).get("display_name", "")
            biblio = item.get("biblio", {})
            doi    = item.get("doi","").replace("https://doi.org/","")
            articles.append({
                "title":   item.get("title","").rstrip("."),
                "authors": authors,
                "journal": source,
                "year":    str(item.get("publication_year","")),
                "volume":  str(biblio.get("volume","")),
                "issue":   str(biblio.get("issue","")),
                "pages":   f"{biblio.get('first_page','')}--{biblio.get('last_page','')}".strip("-"),
                "doi":     doi,
                "_source": "OpenAlex",
            })
        return articles
    except Exception:
        return []


def search_semantic_scholar(query: str, max_results: int = 3) -> list:
    """Search Semantic Scholar (AI-powered academic graph)."""
    try:
        r = requests.get(SEMANTIC_BASE,
            params={"query":query,"fields":"title,authors,year,venue,externalIds","limit":max_results}, timeout=10)
        items = r.json().get("data", [])
        articles = []
        for item in items:
            authors = [a.get("name","") for a in item.get("authors",[])]
            ext = item.get("externalIds", {})
            articles.append({
                "title": item.get("title",""), "authors": authors,
                "year": str(item.get("year","")), "journal": item.get("venue",""),
                "doi": ext.get("DOI",""), "pmid": ext.get("PubMed",""),
                "volume":"", "issue":"", "pages":"", "_source": "Semantic Scholar",
            })
        return articles
    except Exception:
        return []


def multi_source_search(query: str, max_per_source: int = 2) -> list:
    """Search all configured databases for a single query and return merged results."""
    results = []
    # PubMed / MEDLINE
    results.extend(search_pubmed(query, max_per_source))
    # Europe PMC (covers PMC + Cochrane + preprints)
    results.extend(search_europe_pmc(query, max_per_source))
    # LILACS (literatura latino-americana)
    results.extend(search_lilacs(query, max_per_source))
    # OpenAlex (busca cinzenta ampliada — sem paywalls de API)
    results.extend(search_openalex(query, max_per_source))
    # Semantic Scholar (fallback / enriquecimento)
    if not results:
        results.extend(search_semantic_scholar(query, max_per_source))
    return results

# =============================================================================
# VANCOUVER FORMATTER
# =============================================================================

def format_vancouver(ref: dict, number: int) -> str:
    authors = ref.get("authors", []) or ["Autor desconhecido"]
    if len(authors) > 6:
        author_str = ", ".join(authors[:6]) + " et al"
    else:
        author_str = ", ".join(authors)
    title   = ref.get("title","Sem titulo").rstrip(".")
    journal = ref.get("journal","")
    year    = ref.get("year","")
    vol, iss, pgs = ref.get("volume",""), ref.get("issue",""), ref.get("pages","")
    doi     = ref.get("doi","")
    pmid    = ref.get("pmid","")
    cit = f"{number}. {author_str}. {title}. {journal}. {year}"
    if vol:  cit += f";{vol}"
    if iss:  cit += f"({iss})"
    if pgs:  cit += f":{pgs}"
    cit += "."
    if doi:  cit += f" {doi}"
    elif pmid: cit += f" PMID:{pmid}"
    return cit

# =============================================================================
# AI FUNCTIONS
# =============================================================================

def get_ai_client(provider: str, api_key: str):
    if provider == "Anthropic (Claude)":
        import anthropic
        return anthropic.Anthropic(api_key=api_key)
    elif provider == "Google (Gemini)":
        from google import genai
        return genai.Client(api_key=api_key)
    else:
        from openai import OpenAI
        return OpenAI(api_key=api_key)

def ai_call(client, provider: str, model: str, prompt: str, max_tokens: int = 8000) -> str:
    if provider == "Anthropic (Claude)":
        resp = client.messages.create(
            model=model, max_tokens=max_tokens,
            messages=[{"role":"user","content":prompt}])
        return resp.content[0].text
    elif provider == "Google (Gemini)":
        from google import genai as _genai
        resp = client.models.generate_content(
            model=model,
            contents=prompt,
            config=_genai.types.GenerateContentConfig(max_output_tokens=max_tokens),
        )
        return resp.text
    else:  # OpenAI
        resp = client.chat.completions.create(
            model=model, max_tokens=max_tokens,
            messages=[{"role":"user","content":prompt}])
        return resp.choices[0].message.content

def repair_truncated_json(raw: str) -> dict | None:
    """Recover partial paragraphs from a truncated JSON response using a depth-counter parser."""
    # Strip markdown code fences
    cleaned = raw
    m = re.search(r"```(?:json)?\s*(.*)", cleaned, re.DOTALL)
    if m:
        cleaned = re.sub(r"`+$", "", m.group(1)).strip()
    # Find the paragraphs array
    arr_m = re.search(r'"paragraphs"\s*:\s*\[', cleaned)
    if not arr_m:
        return None
    content = cleaned[arr_m.end():]
    # Walk the content extracting complete JSON objects via a depth counter
    paragraphs = []
    i = 0
    n = len(content)
    while i < n:
        if content[i] == '{':
            depth = 0
            in_str = False
            esc = False
            j = i
            while j < n:
                c = content[j]
                if esc:
                    esc = False
                elif c == '\\' and in_str:
                    esc = True
                elif c == '"':
                    in_str = not in_str
                elif not in_str:
                    if c == '{':
                        depth += 1
                    elif c == '}':
                        depth -= 1
                        if depth == 0:
                            try:
                                obj = json.loads(content[i:j+1])
                                if "original" in obj:
                                    paragraphs.append(obj)
                            except Exception:
                                pass
                            i = j + 1
                            break
                j += 1
            else:
                break
        elif content[i] == ']':
            break
        else:
            i += 1
    if paragraphs:
        return {
            "paragraphs": paragraphs,
            "reference_map": {},
            "summary": f"Recuperacao parcial: {len(paragraphs)} paragrafo(s) processado(s). O texto era longo demais — foi processado em partes.",
            "changes_detail": [],
            "_truncated": True,
        }
    return None


def extract_json_from_ai(text: str) -> dict | None:
    try:
        return json.loads(text)
    except Exception:
        pass
    match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
    if match:
        try: return json.loads(match.group(1))
        except: pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try: return json.loads(match.group())
        except: pass
    # Last resort: try to recover paragraphs from a truncated response
    recovered = repair_truncated_json(text)
    if recovered:
        return recovered
    return None


CHUNK_CHAR_LIMIT = 2800  # max chars per chunk sent to the AI


def chunk_text(text: str, max_chars: int = CHUNK_CHAR_LIMIT) -> list:
    """Split text at paragraph boundaries into chunks of at most max_chars."""
    paras = [p.strip() for p in re.split(r'\n\s*\n', text) if p.strip()]
    if not paras:
        return [text]
    chunks, cur, cur_len = [], [], 0
    for p in paras:
        if cur_len + len(p) > max_chars and cur:
            chunks.append("\n\n".join(cur))
            cur, cur_len = [p], len(p)
        else:
            cur.append(p)
            cur_len += len(p)
    if cur:
        chunks.append("\n\n".join(cur))
    return chunks

# =============================================================================
# FILE EXTRACTION
# =============================================================================

def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    try:
        import fitz
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        return "\n".join(page.get_text() for page in doc).strip()
    except Exception as e:
        st.error(f"Erro ao ler PDF: {e}")
        return ""

def extract_text_from_docx(docx_bytes: bytes) -> str:
    try:
        from docx import Document
        doc = Document(BytesIO(docx_bytes))
        return "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())
    except Exception as e:
        st.error(f"Erro ao ler DOCX: {e}")
        return ""

# =============================================================================
# AI PIPELINE
# =============================================================================

def extract_ref_metadata_ai(client, provider, model, pdf_text, filename) -> dict:
    prompt = f"""Extraia metadados bibliograficos deste artigo cientifico.
Retorne APENAS JSON valido:
{{"title":"","authors":["Sobrenome AB"],"journal":"","year":"","volume":"","issue":"","pages":"","doi":"","abstract":"resumo em ate 200 palavras","key_topics":["topico1"]}}

TEXTO ({filename}, primeiros 5000 chars):
{pdf_text[:5000]}"""
    raw  = ai_call(client, provider, model, prompt, max_tokens=1200)
    data = extract_json_from_ai(raw)
    if data:
        data["_source"] = filename
        data["_raw_extracted"] = True
        return data
    return {"title":filename,"authors":[],"journal":"","year":"","volume":"","issue":"","pages":"","doi":"","abstract":pdf_text[:300],"_source":filename}

def identify_citation_needs(client, provider, model, text, mode) -> dict:
    """Identify citation needs and generate PubMed queries for a chunk of text."""
    if mode == "add":
        task  = ("The text has NO citations. For each paragraph with scientific/factual claims, "
                 "generate 1-3 specific PubMed queries in English to find supporting references.")
        extra = ('"needs_citations":true,'
                 '"pubmed_queries":["specific english query 1","specific english query 2"]')
    else:
        task  = ("The text ALREADY HAS citations. Identify problems (wrong, missing, duplicate) "
                 "and generate PubMed queries in English to find correct references.")
        extra = ('"existing_citations":["[1]"],"issues":["description"],'
                 '"pubmed_queries":["specific english query"]')
    prompt = f"""You are a scientific citation specialist (Vancouver format).
TASK: {task}

Rules for generating PubMed queries:
- Write queries in English, specific enough to find real papers
- Include key medical/scientific terms from the paragraph
- Use terms like: "systematic review", "meta-analysis", "clinical trial" when appropriate
- Aim for queries that return recent (last 10 years) high-quality papers

Output ONLY valid JSON (no markdown):
{{"paragraphs":[{{"index":0,"text_preview":"first 80 chars of paragraph",{extra},"needs_web_search":true}}]}}

TEXT:
{text}"""
    raw  = ai_call(client, provider, model, prompt, max_tokens=4000)
    data = extract_json_from_ai(raw)
    return data if data else {"paragraphs":[]}

def _build_ref_catalogue(refs: list) -> str:
    cat = ""
    for i, r in enumerate(refs, 1):
        cat += f"\n[REF{i}] Titulo: {r.get('title','')}\n"
        cat += f"  Autores: {', '.join(r.get('authors',[]))}\n"
        cat += f"  Periodico: {r.get('journal','')} {r.get('year','')}\n"
        if r.get("abstract"):
            cat += f"  Resumo: {r['abstract'][:200]}\n"
    return cat or "(nenhuma referencia disponivel -- use [?])"


def _insert_citations_chunk(client, provider, model, chunk_text, ref_catalogue, mode) -> dict:
    """Run citation insertion on a single text chunk and return parsed dict."""
    if mode == "add":
        instructions = """INSTRUCOES (Adicionar Citacoes):
1. Percorra paragrafo a paragrafo
2. Afirmacoes cientificas/factuais: adicione [N] ao FINAL do paragrafo
3. Use referencias do catalogo quando pertinentes
4. Se precisar de referencia ausente, marque [?]
5. Nao modifique o texto original -- apenas acrescente a citacao"""
    else:
        instructions = """INSTRUCOES (Revisar Citacoes):
1. Verifique cada citacao existente
2. Se incorreta/inadequada, substitua pela correta do catalogo
3. Se nao houver adequada, substitua por [?]
4. Corrija formatacao Vancouver quando necessario"""

    prompt = f"""Especialista em citacoes cientificas Vancouver.
{instructions}

CATALOGO DE REFERENCIAS:
{ref_catalogue}

TEXTO ORIGINAL:
{chunk_text}

Retorne APENAS JSON valido (sem markdown):
{{"paragraphs":[{{"original":"texto original","modified":"texto com citacoes","refs_used":["REF1"],"changes":["descricao"],"changed":true}}],"reference_map":{{"1":"REF1"}},"summary":"resumo","changes_detail":["..."]}}"""

    raw  = ai_call(client, provider, model, prompt, max_tokens=8000)
    data = extract_json_from_ai(raw)
    return data if data else {"error": "Falha no processamento", "raw": raw}


def insert_citations_ai(client, provider, model, text, refs, mode) -> dict:
    ref_catalogue = _build_ref_catalogue(refs)
    chunks = chunk_text(text, max_chars=CHUNK_CHAR_LIMIT)

    if len(chunks) == 1:
        return _insert_citations_chunk(client, provider, model, chunks[0], ref_catalogue, mode)

    # ── Multi-chunk: process each chunk and merge ────────────────────────────
    all_paragraphs   = []
    all_ref_maps     = {}
    all_changes      = []
    chunk_summaries  = []
    has_error        = False

    chunk_bar = st.progress(0, text=f"Processando em {len(chunks)} partes...")
    for idx, chunk in enumerate(chunks, 1):
        chunk_bar.progress(idx / len(chunks),
                           text=f"Processando parte {idx}/{len(chunks)}...")
        result = _insert_citations_chunk(client, provider, model, chunk, ref_catalogue, mode)
        if "error" in result and "paragraphs" not in result:
            has_error = True
            all_paragraphs.append({
                "original": chunk[:200] + "...",
                "modified": chunk[:200] + "...",
                "refs_used": [],
                "changes": [f"Erro no chunk {idx}: {result.get('error','')}"],
                "changed": False,
            })
        else:
            all_paragraphs.extend(result.get("paragraphs", []))
            all_ref_maps.update(result.get("reference_map", {}))
            all_changes.extend(result.get("changes_detail", []))
            if result.get("summary"):
                chunk_summaries.append(f"Parte {idx}: {result['summary']}")
    chunk_bar.empty()

    return {
        "paragraphs":    all_paragraphs,
        "reference_map": all_ref_maps,
        "summary":       " | ".join(chunk_summaries) if chunk_summaries else "Texto processado em multiplas partes.",
        "changes_detail": all_changes,
        "_chunked":      True,
        "_num_chunks":   len(chunks),
    }

# =============================================================================
# MAIN PIPELINE
# =============================================================================

def run_pipeline(client, provider, model, main_text, ref_files, mode, library_refs):
    progress = st.progress(0, text="Iniciando...")
    log      = st.empty()
    def upd(pct, msg):
        progress.progress(pct / 100, text=msg)
        log.caption(f"... {msg}")

    # ── 1. Extract PDF reference metadata ────────────────────────────────────
    ref_metadata = list(library_refs)
    if ref_files:
        upd(5, f"Analisando {len(ref_files)} artigo(s) de referencia com IA...")
        for i, f in enumerate(ref_files):
            pdf_text = extract_text_from_pdf(f.read())
            meta     = extract_ref_metadata_ai(client, provider, model, pdf_text, f.name)
            ref_metadata.append(meta)
            upd(5 + int(15*(i+1)/len(ref_files)),
                f"Artigo {i+1}/{len(ref_files)}: {meta.get('title','')[:50]}...")

    # ── 2. Identify citation needs PER CHUNK ──────────────────────────────────
    # Chunk the text so identify_citation_needs is never called with too many tokens
    text_chunks = chunk_text(main_text, max_chars=CHUNK_CHAR_LIMIT)
    n_chunks    = len(text_chunks)
    upd(20, f"Identificando necessidades de citacao em {n_chunks} parte(s)...")

    all_queries = []
    for ci, chunk in enumerate(text_chunks):
        needs_data = identify_citation_needs(client, provider, model, chunk, mode)
        for p in needs_data.get("paragraphs", []):
            all_queries.extend(p.get("pubmed_queries", []))
        upd(20 + int(10 * (ci+1) / n_chunks),
            f"Analise parte {ci+1}/{n_chunks}: {len(all_queries)} queries geradas")

    # Dedup queries; allow up to 4 queries per chunk (minimum 8)
    all_queries  = list(dict.fromkeys(q for q in all_queries if q.strip()))
    max_searches = max(8, n_chunks * 4)
    all_queries  = all_queries[:max_searches]

    # ── 3. Fallback: se nenhuma query foi gerada, extrair topico do texto ─────
    if not all_queries:
        upd(30, "Gerando queries de busca a partir do topico do texto...")
        topic_prompt = f"""Read this scientific text excerpt and generate 6 specific PubMed search queries in English to find relevant supporting references. Return ONLY a JSON array of strings: ["query1","query2","query3","query4","query5","query6"]

TEXT (first 1500 chars):
{main_text[:1500]}"""
        raw_q = ai_call(client, provider, model, topic_prompt, max_tokens=500)
        try:
            m = re.search(r"\[.*\]", raw_q, re.DOTALL)
            if m:
                all_queries = json.loads(m.group())[:8]
        except Exception:
            pass

    # ── 4. Multi-source web search ────────────────────────────────────────────
    # Covers: PubMed, Europe PMC (incl. Cochrane/preprints), LILACS, OpenAlex,
    #         Semantic Scholar — busca cinzenta incluida via OpenAlex + Europe PMC PPR
    web_refs = []
    if all_queries:
        upd(35, f"Buscando em {len(all_queries)} queries x 4 bases (PubMed, LILACS, Europe PMC, OpenAlex)...")
        for i, q in enumerate(all_queries):
            pct = 35 + int(25 * (i+1) / len(all_queries))
            upd(pct, f"Busca {i+1}/{len(all_queries)}: {q[:55]}")
            web_refs.extend(multi_source_search(q, max_per_source=2))
            time.sleep(0.25)
        # Extra: preprints / busca cinzenta via Europe PMC
        for q in all_queries[:4]:
            web_refs.extend(search_europe_pmc(q, max_results=2, source_filter="PPR"))
    else:
        upd(60, "Nenhuma query gerada — usando apenas biblioteca local.")

    # Dedup web_refs
    seen, unique_web = set(), []
    for r in web_refs:
        t = r.get("title", "").lower()[:80]
        if t not in seen:
            seen.add(t)
            unique_web.append(r)

    all_refs = ref_metadata + unique_web
    upd(62, f"Total de referencias disponiveis: {len(all_refs)} ({len(ref_metadata)} locais + {len(unique_web)} da web)")

    # ── 5. Insert / review citations ──────────────────────────────────────────
    upd(65, "Inserindo/corrigindo citacoes com IA...")
    result = insert_citations_ai(client, provider, model, main_text, all_refs, mode)
    upd(90, "Montando resultado final...")

    # Resolve reference_map
    ref_map = result.get("reference_map", {})
    final_ref_list = []
    for num_str, ref_id in sorted(ref_map.items(), key=lambda x: int(x[0]) if x[0].isdigit() else 999):
        idx_str = re.sub(r"[^0-9]","",ref_id)
        if idx_str:
            idx = int(idx_str)-1
            if 0 <= idx < len(all_refs):
                final_ref_list.append(all_refs[idx])
    if not final_ref_list:
        used_ids = []
        for p in result.get("paragraphs",[]):
            for rid in p.get("refs_used",[]):
                if rid not in used_ids: used_ids.append(rid)
        for uid in used_ids:
            idx_str = re.sub(r"[^0-9]","",uid)
            if idx_str:
                idx = int(idx_str)-1
                if 0 <= idx < len(all_refs):
                    final_ref_list.append(all_refs[idx])

    upd(100, "Concluido!")
    log.empty(); progress.empty()
    return result, all_refs, final_ref_list

# =============================================================================
# DOCX EXPORT
# =============================================================================

def generate_docx(paragraphs: list, final_ref_list: list, mode: str) -> bytes:
    """Build a formatted Word document with the processed text and references."""
    from docx import Document as DocxDoc
    from docx.shared import Pt, Cm, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    doc = DocxDoc()

    # ── Page margins ────────────────────────────────────────────────────────
    for section in doc.sections:
        section.top_margin    = Cm(2.5)
        section.bottom_margin = Cm(2.5)
        section.left_margin   = Cm(3.0)
        section.right_margin  = Cm(2.0)

    # ── Styles ──────────────────────────────────────────────────────────────
    normal_style = doc.styles["Normal"]
    normal_style.font.name = "Times New Roman"
    normal_style.font.size = Pt(12)

    # ── Header strip ────────────────────────────────────────────────────────
    hdr = doc.add_paragraph()
    hdr.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = hdr.add_run("CitacaoIA  -  Texto com Citacoes Vancouver")
    run.bold = True
    run.font.size = Pt(14)
    run.font.color.rgb = RGBColor(0x1E, 0x3A, 0x5F)

    sub = doc.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sub.add_run(f"Gerado em {datetime.now().strftime('%d/%m/%Y %H:%M')}  |  "
                f"Modo: {'Adicionar citacoes' if mode == 'add' else 'Revisar citacoes'}"
                ).font.size = Pt(10)

    doc.add_paragraph()  # spacer

    # ── Body paragraphs ─────────────────────────────────────────────────────
    for p in paragraphs:
        text = p.get("modified") or p.get("original", "")
        if not text.strip():
            continue
        para = doc.add_paragraph()
        para.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        para.paragraph_format.space_after = Pt(6)
        para.paragraph_format.first_line_indent = Cm(1.25)

        # Highlight citation markers [N] in blue
        parts = re.split(r"(\[\??\d*\??\])", text)
        for part in parts:
            run = para.add_run(part)
            run.font.name = "Times New Roman"
            run.font.size = Pt(12)
            if re.match(r"\[\??\d*\??\]", part):
                run.font.color.rgb = RGBColor(0x2E, 0x7D, 0xDB)
                run.bold = True

    # ── References section ──────────────────────────────────────────────────
    doc.add_paragraph()
    ref_hdr = doc.add_paragraph()
    ref_hdr.alignment = WD_ALIGN_PARAGRAPH.LEFT
    rh = ref_hdr.add_run("REFERENCIAS")
    rh.bold = True
    rh.font.size = Pt(12)
    rh.font.color.rgb = RGBColor(0x1E, 0x3A, 0x5F)

    # Separator line
    sep = doc.add_paragraph()
    sep.add_run("_" * 60).font.size = Pt(9)

    if final_ref_list:
        for i, r in enumerate(final_ref_list, 1):
            ref_text = format_vancouver(r, i)
            rp = doc.add_paragraph(style="Normal")
            rp.paragraph_format.left_indent  = Cm(0.5)
            rp.paragraph_format.space_after  = Pt(4)
            rr = rp.add_run(ref_text)
            rr.font.size = Pt(10)
            rr.font.name = "Times New Roman"
    else:
        np_para = doc.add_paragraph()
        np_para.add_run("(Referencias nao resolvidas — verifique o catalogo)").italic = True

    # ── Serialize to bytes ───────────────────────────────────────────────────
    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()


# =============================================================================
# RESULTS DISPLAY
# =============================================================================

def display_results(result, all_refs, final_ref_list, mode):
    if "error" in result and not result.get("paragraphs"):
        st.error(f"Erro: {result.get('error')}")
        with st.expander("Ver resposta bruta"):
            st.text(result.get("raw",""))
        return

    st.success("Processamento concluido com sucesso!")
    paragraphs = result.get("paragraphs", [])
    changed    = [p for p in paragraphs if p.get("changed")]

    c1,c2,c3,c4 = st.columns(4)
    c1.metric("Paragrafos analisados", len(paragraphs))
    c2.metric("Paragrafos alterados",  len(changed))
    c3.metric("Referencias encontradas", len(all_refs))
    c4.metric("Referencias no texto",  len(final_ref_list))
    st.divider()

    if result.get("summary"):
        st.info(f"Resumo: {result['summary']}")
    if result.get("changes_detail"):
        with st.expander("Log detalhado de alteracoes"):
            for line in result["changes_detail"]:
                st.markdown(f"- {line}")
    st.divider()

    tab_final, tab_compare, tab_refs = st.tabs(
        ["Texto Final com Citacoes", "Comparacao Paragrafo a Paragrafo", "Lista de Referencias"])

    with tab_final:
        body = "\n\n".join(p.get("modified") or p.get("original","") for p in paragraphs)
        ref_lines = ["\n\n" + "-"*60, "REFERENCIAS", "-"*60]
        if final_ref_list:
            for i,r in enumerate(final_ref_list,1): ref_lines.append(format_vancouver(r,i))
        else:
            ref_lines.append("(referencias nao resolvidas)")
        full = body + "\n".join(ref_lines)
        st.text_area("", value=full, height=500, label_visibility="collapsed")

        col_dl1, col_dl2 = st.columns(2)
        with col_dl1:
            st.download_button(
                "📥 Baixar texto (.txt)",
                data=full.encode("utf-8"),
                file_name="texto_citacoes_vancouver.txt",
                mime="text/plain",
                use_container_width=True,
            )
        with col_dl2:
            try:
                docx_bytes = generate_docx(paragraphs, final_ref_list, mode)
                st.download_button(
                    "📄 Baixar Word (.docx)",
                    data=docx_bytes,
                    file_name="texto_citacoes_vancouver.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    use_container_width=True,
                    type="primary",
                )
            except Exception as e_docx:
                st.warning(f"Nao foi possivel gerar o .docx: {e_docx}")

    with tab_compare:
        if not paragraphs:
            st.info("Nenhum paragrafo encontrado.")
        else:
            for i,p in enumerate(paragraphs):
                is_ch = p.get("changed",False)
                pill  = '<span class="pill-changed">Alterado</span>' if is_ch else '<span class="pill-ok">Sem alteracao</span>'
                with st.expander(f"Paragrafo {i+1}  {pill}", expanded=is_ch):
                    if is_ch:
                        ca,cb = st.columns(2)
                        with ca:
                            st.markdown("**Original:**")
                            st.markdown(f"<div style='background:#fff3cd;padding:.7rem;border-radius:6px'>{p.get('original','')}</div>", unsafe_allow_html=True)
                        with cb:
                            st.markdown("**Com citacoes:**")
                            st.markdown(f"<div style='background:#d4edda;padding:.7rem;border-radius:6px'>{p.get('modified','')}</div>", unsafe_allow_html=True)
                        if p.get("changes"):
                            st.caption(" | ".join(p["changes"]))
                    else:
                        st.markdown(p.get("original",""))

    with tab_refs:
        disp = final_ref_list if final_ref_list else all_refs
        if not disp:
            st.info("Nenhuma referencia processada.")
        else:
            for i,r in enumerate(disp,1):
                src = r.get("_source","")
                with st.expander(f"[{i}] {r.get('title','')[:80]}...  ({src})"):
                    st.markdown(f"**Autores:** {', '.join(r.get('authors',[]))}")
                    st.markdown(f"**Periodico:** {r.get('journal','N/A')}  **Ano:** {r.get('year','N/A')}")
                    if r.get("doi"): st.markdown(f"**DOI:** {r['doi']}")
                    if r.get("pmid"): st.markdown(f"**PubMed:** [PMID {r['pmid']}](https://pubmed.ncbi.nlm.nih.gov/{r['pmid']}/)")
                    st.markdown(f"<div class='ref-box'>{format_vancouver(r,i)}</div>", unsafe_allow_html=True)
                    # Save to library button
                    if st.button(f"Salvar na biblioteca", key=f"save_ref_{i}"):
                        _, is_new = add_to_library(r)
                        if is_new:
                            st.success("Artigo salvo na biblioteca local!")
                        else:
                            st.info("Artigo ja esta na biblioteca (dados atualizados).")
                        st.rerun()

# =============================================================================
# SIDEBAR
# =============================================================================

def _fetch_gemini_models(api_key: str) -> list:
    """Fetch available Gemini models dynamically from the API."""
    try:
        from google import genai as _genai
        _client = _genai.Client(api_key=api_key)
        all_models = list(_client.models.list())
        fetched = []
        for m in all_models:
            name = m.name if isinstance(m.name, str) else str(m.name)
            name = name.replace("models/", "")
            if "gemini" not in name.lower():
                continue
            # Include only models that support generateContent
            supported = getattr(m, "supported_actions", None) or []
            if "generateContent" in supported or not supported:
                fetched.append(name)
        # Prefer flash/pro order, filter out embedding-only models
        fetched = [n for n in fetched if "embed" not in n.lower()]
        return fetched if fetched else ["gemini-1.5-flash", "gemini-1.5-pro"]
    except Exception:
        return ["gemini-1.5-flash", "gemini-1.5-pro"]


def render_sidebar():
    with st.sidebar:
        st.markdown("## Configuracao da IA")
        provider = st.selectbox("Provedor", ["Anthropic (Claude)","Google (Gemini)","OpenAI (GPT)"])

        # Labels / URLs per provider
        if provider == "Anthropic (Claude)":
            api_lbl = "Chave API Anthropic"
            api_url = "https://console.anthropic.com"
        elif provider == "Google (Gemini)":
            api_lbl = "Chave API Google AI Studio"
            api_url = "https://aistudio.google.com/app/apikey"
        else:
            api_lbl = "Chave API OpenAI"
            api_url = "https://platform.openai.com/api-keys"

        # API key FIRST — Gemini needs it to list models dynamically
        api_key = st.text_input(api_lbl, type="password")
        if api_key:
            st.success("Chave configurada")
        else:
            st.warning(f"[Obter chave aqui]({api_url})")

        # Model selection
        if provider == "Anthropic (Claude)":
            models = ["claude-opus-4-5", "claude-sonnet-4-5", "claude-haiku-4-5-20251001"]
        elif provider == "Google (Gemini)":
            if api_key:
                # Cache per (truncated) key so we don't re-fetch on every render
                cache_key = f"gemini_models_{api_key[:12]}"
                if cache_key not in st.session_state:
                    with st.spinner("Listando modelos Gemini disponiveis..."):
                        st.session_state[cache_key] = _fetch_gemini_models(api_key)
                models = st.session_state[cache_key]
                if st.button("Atualizar lista de modelos", key="btn_refresh_gemini"):
                    st.session_state.pop(cache_key, None)
                    st.rerun()
            else:
                models = ["gemini-1.5-flash", "gemini-1.5-pro"]
        else:
            models = ["gpt-4o", "gpt-4-turbo", "gpt-3.5-turbo"]

        model = st.selectbox("Modelo", models)

        st.divider()
        st.markdown("### Como usar")
        st.markdown("""
<span class="step-badge">1</span> Configure a chave API
<span class="step-badge">2</span> Veja/adicione artigos na Biblioteca
<span class="step-badge">3</span> Selecione modo e insira texto
<span class="step-badge">4</span> Processe e baixe o resultado
""", unsafe_allow_html=True)
        st.divider()
        lib = load_library()
        st.caption(f"Biblioteca local: {len(lib)} artigo(s) salvo(s)")
        if lib:
            st.caption(f"Arquivo: {BIBLIOTECA_FILE}")
    return api_key, provider, model

# =============================================================================
# BIBLIOTECA TAB
# =============================================================================

def render_biblioteca_tab():
    st.markdown("### Biblioteca de Artigos")
    st.caption("Artigos salvos localmente. Ficam disponiveis em todas as sessoes futuras.")

    # ── ADD BY DOI ────────────────

    # ── ADD BY DOI ────────────────────────────────────────────────────────────
    if "doi_article_found" not in st.session_state:
        st.session_state["doi_article_found"] = None
    if "doi_msg" not in st.session_state:
        st.session_state["doi_msg"] = ""

    with st.expander("+ Adicionar artigo por DOI", expanded=True):
        col_doi, col_btn = st.columns([4, 1])
        with col_doi:
            doi_input = st.text_input("DOI do artigo", placeholder="10.1038/s41586-023-00001-0",
                                      label_visibility="collapsed", key="doi_input")
        with col_btn:
            do_lookup = st.button("Buscar", use_container_width=True, type="primary", key="btn_doi")

        if do_lookup:
            if doi_input.strip():
                with st.spinner("Buscando metadados via CrossRef..."):
                    found = lookup_doi(doi_input.strip())
                if found:
                    st.session_state["doi_article_found"] = found
                    st.session_state["doi_msg"] = "ok"
                else:
                    st.session_state["doi_article_found"] = None
                    st.session_state["doi_msg"] = "notfound"
            else:
                st.session_state["doi_msg"] = "empty"

        if st.session_state["doi_msg"] == "notfound":
            st.error("DOI nao encontrado no CrossRef. Verifique o DOI ou adicione manualmente.")
        elif st.session_state["doi_msg"] == "empty":
            st.warning("Digite um DOI antes de buscar.")

        found_art = st.session_state.get("doi_article_found")
        found_art = st.session_state.get("doi_article_found")
        if found_art:
            st.success(f"Encontrado: **{found_art.get('title','(sem titulo)')}**")
            st.caption(
                f"Autores: {', '.join(found_art.get('authors',[]))}  |  "
                f"{found_art.get('journal','')} {found_art.get('year','')}"
            )
            if st.button("Salvar este artigo na biblioteca", type="primary",
                         key="btn_save_doi"):
                _, is_new = add_to_library(found_art)
                st.session_state["doi_article_found"] = None
                st.session_state["doi_msg"] = ""
                if is_new:
                    st.success("Artigo salvo na biblioteca!")
                else:
                    st.info("Artigo atualizado na biblioteca.")
                st.rerun()

    # ── ADD MANUAL ────────────────────────────────────────────────────────────
    with st.expander("+ Adicionar artigo manualmente"):
        with st.form("form_manual"):
            m_title   = st.text_input("Titulo*")
            m_authors = st.text_input("Autores (Sobrenome AB, Sobrenome CD)",
                                      placeholder="Smith AB, Jones CD")
            mc1, mc2, mc3 = st.columns(3)
            m_journal = mc1.text_input("Periodico")
            m_year    = mc2.text_input("Ano")
            m_volume  = mc3.text_input("Volume")
            mc4, mc5 = st.columns(2)
            m_issue   = mc4.text_input("Numero")
            m_pages   = mc5.text_input("Paginas")
            m_doi     = st.text_input("DOI (opcional)")
            m_abstract= st.text_area("Resumo (opcional)", height=80)
            submitted = st.form_submit_button("Salvar na biblioteca", type="primary")
            if submitted:
                if m_title.strip():
                    art = {
                        "title":    m_title.strip(),
                        "authors":  [a.strip() for a in m_authors.split(",") if a.strip()],
                        "journal":  m_journal.strip(),
                        "year":     m_year.strip(),
                        "volume":   m_volume.strip(),
                        "issue":    m_issue.strip(),
                        "pages":    m_pages.strip(),
                        "doi":      m_doi.strip(),
                        "abstract": m_abstract.strip(),
                    }
                    _, is_new = add_to_library(art)
                    st.success("Artigo salvo!" if is_new else "Artigo atualizado!")
                    st.rerun()
                else:
                    st.error("O titulo e obrigatorio.")

    # ── LIBRARY DISPLAY ───────────────────────────────────────────────────────
    lib = load_library()
    st.divider()
    if not lib:
        st.info("Biblioteca vazia. Adicione artigos por DOI, manualmente, "
                "ou fazendo upload de PDFs na aba de citacoes.")
        return

    col_s, col_sort = st.columns([4, 1])
    search_q = col_s.text_input("Buscar na biblioteca",
                                placeholder="titulo, autor, periodico...",
                                label_visibility="collapsed")
    sort_by  = col_sort.selectbox("Ordenar", ["Mais recente", "Ano", "Titulo"],
                                  label_visibility="collapsed")

    filtered = lib
    if search_q:
        q = search_q.lower()
        filtered = [a for a in lib if
                    q in a.get("title","").lower() or
                    q in " ".join(a.get("authors",[])).lower() or
                    q in a.get("journal","").lower()]

    if sort_by == "Ano":
        filtered = sorted(filtered, key=lambda x: x.get("year","0"), reverse=True)
    elif sort_by == "Titulo":
        filtered = sorted(filtered, key=lambda x: x.get("title","").lower())

    st.caption(f"Exibindo {len(filtered)} de {len(lib)} artigo(s)")

    for i, art in enumerate(filtered):
        orig_idx = lib.index(art) if art in lib else i
        st.markdown(
            f'<div class="art-card">'
            f'<div class="art-title">{art.get("title","(sem titulo)")}</div>'
            f'<div class="art-meta">'
            f'{", ".join(art.get("authors",[])[:3])}'
            f'{"..." if len(art.get("authors",[])) > 3 else ""}'
            f' &nbsp;|&nbsp; <em>{art.get("journal","")}</em> {art.get("year","")}'
            f'{" &nbsp;|&nbsp; DOI: " + art.get("doi","") if art.get("doi") else ""}'
            f'</div></div>', unsafe_allow_html=True)
        col_a, col_b = st.columns([5, 1])
        if art.get("abstract"):
            with col_a:
                with st.expander("Ver resumo"):
                    st.caption(art["abstract"])
        with col_b:
            if st.button("Remover", key=f"del_{orig_idx}_{art.get('title','')[:10]}"):
                delete_from_library(orig_idx)
                st.rerun()


# =============================================================================
# CITAR TAB
# =============================================================================

def render_citar_tab():
    st.markdown("### Processar Texto")

    api_key  = st.session_state.get("_api_key", "")
    provider = st.session_state.get("_provider", "")
    model    = st.session_state.get("_model", "")

    if not api_key:
        st.warning("Configure a chave API na barra lateral antes de processar.")
        return

    mode = st.radio(
        "Modo de operacao:",
        ["Adicionar citacoes (texto sem citacoes)",
         "Revisar citacoes (texto ja citado)"],
        horizontal=True,
    )
    mode_key = "add" if "Adicionar" in mode else "review"

    st.markdown("#### Texto principal")
    tab_up, tab_paste = st.tabs(["Upload (PDF ou Word)", "Colar texto"])
    text_file   = None
    pasted_text = ""
    with tab_up:
        text_file = st.file_uploader("Upload PDF ou Word", type=["pdf","docx"],
                                     key="main_upload")
        if text_file:
            st.success(f"{text_file.name} carregado")
    with tab_paste:
        pasted_text = st.text_area(
            "Cole seu texto aqui:", height=260,
            placeholder="Cole o texto do artigo, capitulo ou secao aqui...")

    st.markdown("#### Referencias (opcional)")
    st.caption("Upload de PDFs dos artigos de referencia para extracao de metadados. "
               "Sem upload, o app busca referencias automaticamente em "
               "PubMed, LILACS, Europe PMC e OpenAlex.")
    ref_files = st.file_uploader("PDFs de referencia", type=["pdf"],
                                  accept_multiple_files=True, key="ref_upload")

    use_library  = st.checkbox("Incluir artigos da biblioteca local como referencias", value=True)
    library_refs = load_library() if use_library else []

    if ref_files:
        st.info(f"{len(ref_files)} PDF(s) de referencia carregado(s).")

    st.divider()
    run_btn = st.button("Processar texto com IA", type="primary",
                        use_container_width=True, disabled=not api_key)

    if run_btn:
        main_text = ""
        if text_file:
            b = text_file.read()
            main_text = extract_text_from_pdf(b) if text_file.name.lower().endswith(".pdf") \
                        else extract_text_from_docx(b)
        else:
            main_text = pasted_text.strip()

        if not main_text:
            st.error("Insira o texto principal (upload ou colagem).")
            return

        try:
            client = get_ai_client(provider, api_key)
        except Exception as e:
            st.error(f"Erro ao inicializar cliente IA: {e}")
            return

        result, all_refs, final_ref_list = run_pipeline(
            client, provider, model, main_text, ref_files, mode_key, library_refs)
        st.session_state["last_result"]     = result
        st.session_state["last_all_refs"]   = all_refs
        st.session_state["last_final_refs"] = final_ref_list
        st.session_state["last_mode"]       = mode_key

    if st.session_state.get("last_result"):
        display_results(
            st.session_state["last_result"],
            st.session_state["last_all_refs"],
            st.session_state["last_final_refs"],
            st.session_state.get("last_mode","add"),
        )


# =============================================================================
# EMBASE SEARCH (via Elsevier API ou Europe PMC fallback)
# =============================================================================

def search_embase(query: str, max_results: int = 3,
                  elsevier_key: str = "") -> list:
    """Search EMBASE.
    If an Elsevier Institutional API key is provided, uses the official API.
    Otherwise falls back to Europe PMC which indexes EMBASE-derived content."""
    articles = []

    # -- Strategy 1: Elsevier Embase API (requires institutional key) ----------
    if elsevier_key:
        try:
            r = requests.get(
                "https://api.elsevier.com/content/search/sciencedirect",
                params={
                    "query":   query,
                    "count":   max_results,
                    "field":   "title,creator,publicationName,coverDate,doi,description",
                    "apiKey":  elsevier_key,
                },
                headers={"Accept": "application/json"},
                timeout=12,
            )
            if r.status_code == 200:
                entries = r.json().get("search-results",{}).get("entry",[])
                for e in entries[:max_results]:
                    articles.append({
                        "title":   e.get("dc:title","").rstrip("."),
                        "authors": [e.get("dc:creator","")],
                        "journal": e.get("prism:publicationName",""),
                        "year":    str(e.get("prism:coverDate",""))[:4],
                        "doi":     e.get("prism:doi",""),
                        "_source": "EMBASE/Elsevier",
                    })
        except Exception:
            pass

    # -- Strategy 2: Europe PMC with EMBASE-indexed sources --------------------
    if not articles:
        try:
            r = requests.get(
                "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
                params={
                    "query":      query + " (SRC:MED OR SRC:PMC OR SRC:AGR)",
                    "resultType": "core",
                    "pageSize":   max_results,
                    "format":     "json",
                },
                timeout=12,
            )
            results = r.json().get("resultList",{}).get("result",[])
            for item in results:
                au_list = item.get("authorList",{}).get("author",[])
                authors = [f"{a.get('lastName','')} {a.get('initials','')}".strip()
                           for a in (au_list if isinstance(au_list, list) else [])]
                articles.append({
                    "title":   item.get("title","").rstrip("."),
                    "authors": authors,
                    "journal": item.get("journalTitle",""),
                    "year":    str(item.get("pubYear","")),
                    "volume":  item.get("journalVolume",""),
                    "issue":   item.get("issue",""),
                    "pages":   item.get("pageInfo",""),
                    "doi":     item.get("doi",""),
                    "pmid":    item.get("pmid",""),
                    "_source": "EMBASE/Europe PMC",
                })
        except Exception:
            pass

    return articles


# Patch multi_source_search to include EMBASE
_orig_multi = multi_source_search  # keep reference

def multi_source_search(query: str, max_per_source: int = 2,
                        elsevier_key: str = "") -> list:
    """Search all configured databases including EMBASE."""
    results = []
    results.extend(search_pubmed(query, max_per_source))
    results.extend(search_europe_pmc(query, max_per_source))
    results.extend(search_embase(query, max_per_source, elsevier_key))
    results.extend(search_lilacs(query, max_per_source))
    results.extend(search_openalex(query, max_per_source))
    if not results:
        results.extend(search_semantic_scholar(query, max_per_source))
    return results


# =============================================================================
# TEXT REVISION AI  (ortografia, gramatica, estilo, redundancia)
# =============================================================================

def revise_text_ai(client, provider, model, text: str) -> dict:
    """Run editorial revision on a text chunk."""
    prompt = f"""You are a senior scientific editor at a top medical publisher.
Your job: revise the following text with the same rigour applied to best-selling academic books.

Review for ALL of the following:
1. ORTHOGRAPHY — spelling errors, wrong accents, typos
2. GRAMMAR — subject-verb agreement, tense consistency, pronoun reference, syntax
3. STYLE — passive voice overuse, overly complex sentences (split them), weak verbs
4. REDUNDANCY — repeated ideas within or across paragraphs; remove without losing meaning
5. SCIENTIFIC CLARITY — imprecise or ambiguous scientific statements; improve precision
6. COHESION — improve transitions between paragraphs when weak

Rules:
- Preserve all citations like [1], [2], [?] exactly as they appear
- Preserve headings (lines that are titles/subtitles)
- Do NOT add or remove citations
- Keep the author's voice and scientific content intact
- For each paragraph, list the specific issues found

Return ONLY valid JSON (no markdown fences):
{{"paragraphs":[{{"original":"exact original text","revised":"corrected text","issues":["issue 1","issue 2"],"changed":true}}],"summary":"overall editorial assessment in Portuguese","overall_quality":"Bom/Regular/Requer revisao extensiva"}}

TEXT TO REVISE:
{text}"""

    raw  = ai_call(client, provider, model, prompt, max_tokens=8000)
    data = extract_json_from_ai(raw)
    return data if data else {"error": "Falha na revisao", "raw": raw}


def run_revision_pipeline(client, provider, model, text: str) -> dict:
    """Run editorial revision across all text chunks and merge."""
    chunks  = chunk_text(text, max_chars=CHUNK_CHAR_LIMIT)
    n       = len(chunks)
    progress = st.progress(0, text="Iniciando revisao editorial...")
    log      = st.empty()

    all_paragraphs  = []
    all_summaries   = []
    quality_scores  = []

    for i, chunk in enumerate(chunks, 1):
        progress.progress(i / n, text=f"Revisando parte {i}/{n}...")
        result = revise_text_ai(client, provider, model, chunk)
        if "error" in result and "paragraphs" not in result:
            all_paragraphs.append({
                "original": chunk[:200] + "...",
                "revised":  chunk[:200] + "...",
                "issues":   [f"Erro no chunk {i}: {result.get('error','')}"],
                "changed":  False,
            })
        else:
            all_paragraphs.extend(result.get("paragraphs", []))
            if result.get("summary"):
                all_summaries.append(f"Parte {i}: {result['summary']}")
            if result.get("overall_quality"):
                quality_scores.append(result["overall_quality"])

    progress.empty(); log.empty()

    return {
        "paragraphs":      all_paragraphs,
        "summary":         " | ".join(all_summaries),
        "overall_quality": quality_scores[0] if quality_scores else "N/A",
        "_chunked":        n > 1,
    }


def generate_revision_docx(result: dict) -> bytes:
    """Build a Word document with original vs. revised text side-by-side."""
    from docx import Document as DocxDoc
    from docx.shared import Pt, Cm, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement

    doc = DocxDoc()
    for section in doc.sections:
        section.top_margin    = Cm(2.5)
        section.bottom_margin = Cm(2.5)
        section.left_margin   = Cm(2.5)
        section.right_margin  = Cm(2.0)

    # Header
    hdr = doc.add_paragraph()
    hdr.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = hdr.add_run("CitacaoIA - Revisao Editorial")
    r.bold = True; r.font.size = Pt(14)
    r.font.color.rgb = RGBColor(0x1E, 0x3A, 0x5F)

    sub = doc.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sub.add_run(
        f"Qualidade geral: {result.get('overall_quality','N/A')}  |  "
        f"Gerado em {datetime.now().strftime('%d/%m/%Y %H:%M')}"
    ).font.size = Pt(10)

    if result.get("summary"):
        doc.add_paragraph()
        sp = doc.add_paragraph()
        sp.add_run("Avaliacao editorial: ").bold = True
        sp.add_run(result["summary"]).italic = True

    doc.add_paragraph()

    paragraphs = result.get("paragraphs", [])
    changed = [p for p in paragraphs if p.get("changed")]
    unchanged = [p for p in paragraphs if not p.get("changed")]

    # Section: revised full text
    sec = doc.add_paragraph()
    sec.add_run("TEXTO REVISADO").bold = True
    sec.add_run(f"  ({len(changed)} paragrafos alterados de {len(paragraphs)})").font.size = Pt(10)

    for p in paragraphs:
        text = p.get("revised") or p.get("original","")
        if not text.strip():
            continue
        para = doc.add_paragraph()
        para.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        para.paragraph_format.space_after = Pt(6)
        para.paragraph_format.first_line_indent = Cm(1.25)
        run = para.add_run(text)
        run.font.name = "Times New Roman"
        run.font.size = Pt(12)

    # Section: change log
    doc.add_page_break()
    log_hdr = doc.add_paragraph()
    log_hdr.add_run("LOG DE ALTERACOES").bold = True

    for i, p in enumerate(changed, 1):
        doc.add_paragraph()
        ph = doc.add_paragraph()
        ph.add_run(f"Paragrafo {i}").bold = True
        issues = p.get("issues",[])
        if issues:
            for iss in issues:
                ip = doc.add_paragraph(style="List Bullet")
                ip.add_run(iss).font.size = Pt(10)
        # Original vs Revised
        tbl = doc.add_table(rows=1, cols=2)
        tbl.style = "Table Grid"
        tbl.columns[0].width = Cm(8)
        tbl.columns[1].width = Cm(8)
        hdr_cells = tbl.rows[0].cells
        hdr_cells[0].paragraphs[0].add_run("ORIGINAL").bold = True
        hdr_cells[1].paragraphs[0].add_run("REVISADO").bold = True
        row = tbl.add_row().cells
        orig_p = row[0].add_paragraph(p.get("original",""))
        orig_p.runs[0].font.size = Pt(9)
        rev_p  = row[1].add_paragraph(p.get("revised",""))
        rev_p.runs[0].font.size = Pt(9)
        rev_p.runs[0].font.color.rgb = RGBColor(0x00, 0x60, 0x00)

    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()


def display_revision_results(result: dict):
    """Show revision results in the UI."""
    if "error" in result and "paragraphs" not in result:
        st.error(f"Erro: {result.get('error')}")
        with st.expander("Ver resposta bruta"):
            st.text(result.get("raw",""))
        return

    paragraphs = result.get("paragraphs", [])
    changed    = [p for p in paragraphs if p.get("changed")]
    quality    = result.get("overall_quality","N/A")

    q_color = {"Bom":"#28a745","Regular":"#ffc107","Requer revisao extensiva":"#dc3545"}.get(quality,"#6c757d")
    st.markdown(
        f'<div style="background:{q_color}20;border-left:4px solid {q_color};'
        f'padding:.7rem 1rem;border-radius:0 8px 8px 0;margin-bottom:1rem;">'
        f'<strong>Qualidade geral:</strong> {quality} &nbsp;|&nbsp; '
        f'<strong>{len(changed)}</strong> de <strong>{len(paragraphs)}</strong> paragrafos alterados'
        f'</div>', unsafe_allow_html=True)

    if result.get("summary"):
        st.info(f"Avaliacao editorial: {result['summary']}")

    st.divider()
    tab_full, tab_cmp = st.tabs(["Texto Revisado", "Comparacao Paragrafo a Paragrafo"])

    with tab_full:
        revised_full = "\n\n".join(
            p.get("revised") or p.get("original","") for p in paragraphs)
        st.text_area("", value=revised_full, height=500, label_visibility="collapsed")
        col1, col2 = st.columns(2)
        with col1:
            st.download_button(
                "📥 Baixar revisado (.txt)",
                data=revised_full.encode("utf-8"),
                file_name="texto_revisado.txt",
                mime="text/plain",
                use_container_width=True,
            )
        with col2:
            try:
                docx_bytes = generate_revision_docx(result)
                st.download_button(
                    "📄 Baixar revisado (.docx)",
                    data=docx_bytes,
                    file_name="texto_revisado.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    use_container_width=True,
                    type="primary",
                )
            except Exception as e:
                st.warning(f"Erro ao gerar .docx: {e}")

    with tab_cmp:
        for i, p in enumerate(paragraphs):
            is_ch = p.get("changed", False)
            pill  = ('<span class="pill-changed">Alterado</span>'
                     if is_ch else '<span class="pill-ok">Sem alteracao</span>')
            with st.expander(f"Paragrafo {i+1}  {pill}", expanded=is_ch):
                if is_ch:
                    ca, cb = st.columns(2)
                    with ca:
                        st.markdown("**Original:**")
                        st.text(p.get("original",""))
                    with cb:
                        st.markdown("**Revisado:**")
                        st.text(p.get("revised",""))
                    if p.get("issues"):
                        st.caption("Problemas: " + " | ".join(p["issues"]))
                else:
                    st.text(p.get("original",""))


# =============================================================================
# REVISION TAB
# =============================================================================

def render_revisao_tab():
    st.markdown("### Revisao Editorial do Texto")
    st.caption(
        "Revisao ortografica, gramatical, estilistica e de redundancia — "
        "como um editor senior de publicacoes cientificas.")

    api_key  = st.session_state.get("_api_key","")
    provider = st.session_state.get("_provider","")
    model    = st.session_state.get("_model","")

    if not api_key:
        st.warning("Configure a chave API na barra lateral antes de revisar.")
        return

    tab_up, tab_paste = st.tabs(["Upload (PDF ou Word)", "Colar texto"])
    text_file   = None
    pasted_text = ""
    with tab_up:
        text_file = st.file_uploader("Upload PDF ou Word", type=["pdf","docx"],
                                     key="rev_upload")
        if text_file: st.success(f"{text_file.name} carregado")
    with tab_paste:
        pasted_text = st.text_area("Cole seu texto aqui:", height=260,
                                   placeholder="Cole o texto para revisao...",
                                   key="rev_paste")

    st.divider()

    col_a, col_b = st.columns([3,1])
    with col_a:
        st.markdown("""**O que sera revisado:**
- Ortografia e acentuacao
- Gramatica e concordancia
- Estilo cientifico (voz passiva excessiva, frases longas, verbos fracos)
- Redundancia e repeticoes
- Coesao entre paragrafos""")
    with col_b:
        run_rev = st.button("Revisar texto", type="primary",
                            use_container_width=True, disabled=not api_key)

    if run_rev:
        main_text = ""
        if text_file:
            b = text_file.read()
            main_text = extract_text_from_pdf(b) if text_file.name.lower().endswith(".pdf") \
                        else extract_text_from_docx(b)
        else:
            main_text = pasted_text.strip()

        if not main_text:
            st.error("Insira o texto para revisao.")
            return

        try:
            client = get_ai_client(provider, api_key)
        except Exception as e:
            st.error(f"Erro ao inicializar cliente IA: {e}")
            return

        result = run_revision_pipeline(client, provider, model, main_text)
        st.session_state["last_revision"] = result

    if st.session_state.get("last_revision"):
        display_revision_results(st.session_state["last_revision"])


# =============================================================================
# MAIN
# =============================================================================

def main():
    st.markdown("""<div class="cia-header">
  <h1>CitacaoIA</h1>
  <p>Gestor inteligente de citacoes . Vancouver . PubMed + EMBASE + LILACS + OpenAlex . Powered by IA</p>
</div>""", unsafe_allow_html=True)

    api_key, provider, model = render_sidebar()
    st.session_state["_api_key"]  = api_key
    st.session_state["_provider"] = provider
    st.session_state["_model"]    = model

    for k in ["last_result","last_all_refs","last_final_refs","last_mode","last_revision"]:
        if k not in st.session_state:
            st.session_state[k] = None

    tab_bib, tab_citar, tab_rev = st.tabs([
        "\U0001f4d6 Biblioteca de Artigos",
        "✍️ Processar Texto + Citacoes",
        "\U0001f4dd Revisao Editorial",
    ])
    with tab_bib:
        render_biblioteca_tab()
    with tab_citar:
        render_citar_tab()
    with tab_rev:
        render_revisao_tab()


if __name__ == "__main__":
    main()
