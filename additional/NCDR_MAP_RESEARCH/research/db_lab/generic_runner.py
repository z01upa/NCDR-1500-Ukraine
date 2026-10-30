"""Read-only, capability-checked generic task executor; no user text is executed."""
from __future__ import annotations
import csv, hashlib, html, json, re, sqlite3, uuid
from pathlib import Path

OPERATION_REGISTRY={
 "LOAD_ARTIFACT":{"capabilities":["ARTIFACT_INVENTORY"],"implementation":"find_readonly_artifact"},
 "PE_ANALYZE":{"capabilities":["PE_IMPORT_ANALYSIS"],"implementation":"pe_analyze"},
 "SH4_DISASSEMBLE":{"capabilities":["SH4_DISASSEMBLY"],"implementation":"disassemble_module"},
 "BUILD_CALL_GRAPH":{"capabilities":["SH4_XREF_ANALYSIS"],"implementation":"build_call_graph"},
 "SH4_XREF":{"capabilities":["SH4_XREF_ANALYSIS"],"implementation":"normalized_xrefs"},
 "IMPORT_XREF":{"capabilities":["WINCE_PE_ORDINAL_IMPORTS","SH4_XREF_ANALYSIS"],"implementation":"get_import_xrefs"},
 "STRING_XREF":{"capabilities":["SH4_XREF_ANALYSIS"],"implementation":"get_string_xrefs"},
 "DATA_XREF":{"capabilities":["SH4_XREF_ANALYSIS"],"implementation":"get_data_xrefs"},
 "SEARCH_STRINGS":{"capabilities":["ASCII_UTF16_SCAN"],"implementation":"sh4_strings"},
 "SEARCH_EXTENSIONS":{"capabilities":["ASCII_UTF16_SCAN"],"implementation":"literal_extension_search"},
 "RANK_FUNCTIONS":{"capabilities":["SH4_XREF_ANALYSIS"],"implementation":"rank_static_candidates"},
 "EXPORT_CSV":{"capabilities":[],"implementation":"csv.DictWriter"},
 "GENERATE_REPORT":{"capabilities":["REPORT_GENERATION"],"implementation":"markdown_and_html_report"},
 "PACKAGE_RESULTS":{"capabilities":["PACKAGE_VALIDATION"],"implementation":"package_run"},
 "SH4_CALL_ARGUMENT_TRACE":{"capabilities":["SH4_DISASSEMBLY","SH4_XREF_ANALYSIS","SH4_WINCE_ABI_ANALYSIS"],"implementation":"trace_registers_at_call"},
 "SH4_ABI_ANALYSIS":{"capabilities":["SH4_WINCE_ABI_ANALYSIS"],"implementation":"sh4_wince_abi"},
 "MSVC_DECORATED_SYMBOL_PARSE":{"capabilities":["MSVC_DECORATED_SYMBOL_PARSE"],"implementation":"parse_msvc_decorated_symbol"},
 "READ_RVA_BYTES":{"capabilities":["RVA_DATA_READ"],"implementation":"read_rva_bytes"},
 "HEX_VIEW":{"capabilities":[],"implementation":"hex_view"},
 "ASCII_VIEW":{"capabilities":[],"implementation":"ascii_view"},
 "UTF16LE_VIEW":{"capabilities":[],"implementation":"utf16le_view"},
 "WINDOWS_GUID_INTERPRET":{"capabilities":["GUID_INTERPRETATION"],"implementation":"windows_guid_interpret"},
 "INSPECT_DATA_REGION":{"capabilities":["RVA_DATA_READ","SH4_XREF_ANALYSIS"],"implementation":"inspect_data_region"},
 "SH4_RETURN_VALUE_TRACE":{"capabilities":["SH4_DISASSEMBLY","SH4_VALUE_FLOW_TRACE"],"implementation":"trace_return_value"},
 "SH4_OUT_PARAMETER_TRACE":{"capabilities":["SH4_DISASSEMBLY","SH4_WINCE_ABI_ANALYSIS","SH4_VALUE_FLOW_TRACE"],"implementation":"trace_out_parameter"},
 "SH4_OBJECT_FLOW_TRACE":{"capabilities":["SH4_DISASSEMBLY","SH4_VALUE_FLOW_TRACE"],"implementation":"trace_object_flow"},
 "VTABLE_CALL_DETECTION":{"capabilities":["SH4_DISASSEMBLY","SH4_XREF_ANALYSIS","SH4_VALUE_FLOW_TRACE"],"implementation":"detect_vtable_calls"},
 "OBJECT_FLOW_REPORT":{"capabilities":[],"implementation":"object_flow_report"},
 "CORPUS_BINARY_PATTERN_SEARCH":{"capabilities":["CORPUS_BINARY_PATTERN_SEARCH","MULTI_ARTIFACT_SCOPE"],"implementation":"cataloged raw-byte search"},
 "POSITIVE_CONTROL":{"capabilities":["POSITIVE_CONTROL_VALIDATION","MULTI_ARTIFACT_SCOPE"],"implementation":"cataloged positive-control scan"},
 "PE_FILE_OFFSET_MAPPING":{"capabilities":["PE_FILE_OFFSET_MAPPING"],"implementation":"validated PE section mapping"},
 "CORPUS_CODE_XREF_ANALYSIS":{"capabilities":["CORPUS_CODE_XREF_ANALYSIS","SH4_DISASSEMBLY","SH4_XREF_ANALYSIS"],"implementation":"SH4 xrefs around catalog pattern hits"},
 "CORPUS_STRING_SEARCH":{"capabilities":["CORPUS_STRING_SEARCH","MULTI_ARTIFACT_SCOPE"],"implementation":"cataloged ASCII and UTF-16LE search"},
 "CORPUS_SYMBOL_SEARCH":{"capabilities":["CORPUS_SYMBOL_SEARCH","PE_IMPORT_ANALYSIS","MSVC_DECORATED_SYMBOL_PARSE"],"implementation":"cataloged PE import/export symbol search"},
 "BUILD_RELATIONSHIP_TABLE":{"capabilities":["GUID_RELATIONSHIP_AGGREGATION"],"implementation":"evidence relationship aggregation"},
 "RANK_ARTIFACTS":{"capabilities":["ARTIFACT_RANKING"],"implementation":"weighted evidence ranking"},
 "MULTI_ARTIFACT_SCOPE":{"capabilities":["MULTI_ARTIFACT_SCOPE"],"implementation":"validated firmware/update corpus scope declaration"},
 "POSITIVE_CONTROL_VALIDATION":{"capabilities":["POSITIVE_CONTROL_VALIDATION","MULTI_ARTIFACT_SCOPE"],"implementation":"cataloged positive-control scan","executor_operation":"POSITIVE_CONTROL"},
 "PE_FILE_OFFSET_TO_RVA":{"capabilities":["PE_FILE_OFFSET_MAPPING"],"implementation":"validated PE section mapping","executor_operation":"PE_FILE_OFFSET_MAPPING"},
 "CONDITIONAL_FOCUSED_ANALYSIS":{"capabilities":[],"implementation":"conditional SH4 evidence plan gate"},
 "SH4_XREF_ANALYSIS":{"capabilities":["SH4_XREF_ANALYSIS"],"implementation":"normalized_xrefs","executor_operation":"SH4_XREF"},
}
GUID_LABEL_RE=r"\bGUID(?:[_-][A-Z0-9]{1,3}\b|\s+[A-Z]\b)"

METHOD_RULES=[
 (re.compile(r"search all available.{0,160}(?:EXE.{0,80}HEX|firmware/update).{0,140}do not limit.{0,30}PE",re.I|re.S),"MULTI_ARTIFACT_SCOPE"),
 (re.compile(r"search all available.{0,180}(?:EXE.{0,80}HEX|firmware/update)|all available.{0,140}firmware/update",re.I|re.S),"CORPUS_BINARY_PATTERN_SEARCH"),
 (re.compile(r"positive control|control executable.{0,40}contain|must contain.{0,80}(?:GUID|pattern)|validate.{0,40}control",re.I),"POSITIVE_CONTROL_VALIDATION"),
 (re.compile(r"for every PE32 SH4.{0,100}map file offset.{0,100}(?:section|RVA|VA)",re.I|re.S),"PE_FILE_OFFSET_TO_RVA"),
 (re.compile(r"determine whether the GUID is used|determine whether GUID is used|GUID is used as.{0,200}(?:static data only|unknown)",re.I|re.S),"CORPUS_CODE_XREF_ANALYSIS"),
 (re.compile(r"search the same modules.{0,200}(?:ASCII|UTF.?16LE)",re.I|re.S),"CORPUS_STRING_SEARCH"),
 (re.compile(r"search for decorated C\+\+ symbols.{0,200}(?:Factory|Manager)",re.I|re.S),"CORPUS_SYMBOL_SEARCH"),
 (re.compile(r"investigate GUID[_ -]B.{0,180}GUID[_ -]D",re.I|re.S),"BUILD_RELATIONSHIP_TABLE"),
 (re.compile(r"build a GUID relationship table",re.I),"BUILD_RELATIONSHIP_TABLE"),
 (re.compile(r"if (?:a module other than NAVIMAIN|another module) contains GUID[_ -]A.{0,120}(?:GUID[_ -]D)?.{0,180}focused SH4 analysis",re.I|re.S),"CONDITIONAL_FOCUSED_ANALYSIS"),
 (re.compile(r"search for the canonical GUID text forms?.{0,180}secondary check.{0,500}binary raw search is authoritative",re.I|re.S),"CORPUS_STRING_SEARCH"),
 (re.compile(r"positive control|control executable.{0,40}contain|must contain.{0,80}(?:GUID|pattern)|validate.{0,40}control",re.I),"POSITIVE_CONTROL_VALIDATION"),
 (re.compile(r"raw bytes?|binary patterns?|byte patterns?|byte-for-byte|search.{0,100}(?:binary|raw byte)|(?:all|across the|throughout the)\s*(?:cataloged\s+)?(?:firmware\s+)?artifacts?.{0,100}(?:byte|pattern)|artifact scope.{0,60}(?:binary|raw byte)",re.I),"CORPUS_BINARY_PATTERN_SEARCH"),
 (re.compile(r"file.?offset.{0,30}(?:RVA|VA)|map.{0,35}(?:file offset|offsets).{0,30}(?:RVA|VA)",re.I),"PE_FILE_OFFSET_MAPPING"),
 (re.compile(r"(?:code|data) xrefs?.{0,80}(?:GUID|pattern|match)|(?:GUID|pattern|match).{0,100}(?:code|data) xrefs?|xref analysis.{0,60}(?:match|GUID)|nearby calls.{0,60}(?:GUID|match)|referencing functions.{0,60}(?:hit|GUID)|code xrefs?.{0,60}data xrefs?.{0,80}referencing functions",re.I),"CORPUS_CODE_XREF_ANALYSIS"),
 (re.compile(r"focused SH4 analysis.{0,100}(?:xref|GUID|pattern|match)|SH4 analysis around.{0,60}(?:xref|GUID|pattern|match)",re.I),"CORPUS_CODE_XREF_ANALYSIS"),
 (re.compile(r"(?=.*(?:corpus|cataloged artifacts|all artifacts|across artifacts))(?=.*(?:ASCII|UTF.?16LE))(?=.*(?:search|string|term))",re.I),"CORPUS_STRING_SEARCH"),
 (re.compile(r"(?:imported|exported|decorated).{0,50}symbols?.{0,80}(?:corpus|artifact|PE)|symbol search.{0,40}(?:PE|corpus)|search.{0,50}(?:symbols|decorated names).{0,40}(?:PE|corpus)",re.I),"CORPUS_SYMBOL_SEARCH"),
 (re.compile(r"relationship (?:table|aggregation)|aggregate.{0,40}(?:GUID|artifact).{0,40}(?:relationship|evidence)",re.I),"BUILD_RELATIONSHIP_TABLE"),
 (re.compile(r"rank artifacts?|artifact ranking|weighted evidence.{0,40}(?:rank|score)",re.I),"RANK_ARTIFACTS"),
 (re.compile(r"recover.{0,90}(?:arguments?|machine state|register arguments?|r[4-7]|stack[- ]passed)|machine state.{0,60}before the call|recover.{0,40}before the call|show source of each argument|trace call parameters|arguments?.{0,30}(?:passed|call)|call.?argument|argument layout",re.I),"SH4_CALL_ARGUMENT_TRACE"),
 (re.compile(r"decorated symbol|demangl|microsoft decorated|msvc",re.I),"MSVC_DECORATED_SYMBOL_PARSE"),
 (re.compile(r"(?:export|read|extract).{0,30}\b\d+\s+(?:raw\s+)?bytes?\b.{0,60}(?:rva|address)|(?:rva|address).{0,30}(?:export|read|extract).{0,20}\b\d+\s+bytes?|(?:export|read).{0,30}raw bytes?.{0,30}(?:around|from|at).{0,20}rva|export.{0,25}bytes?.{0,35}around it",re.I),"READ_RVA_BYTES"),
 (re.compile(r"hex.{0,40}ascii.{0,40}utf.?16|hex view|ascii view|utf.?16le view",re.I),"HEX_VIEW"),
 (re.compile(r"test.{0,100}\bguid\b|interpret.{0,30}\bguid\b|forms? a guid|determine whether it is.{0,80}\bguid\b",re.I),"WINDOWS_GUID_INTERPRET"),
 (re.compile(r"inspect.{0,30}(?:data|global).{0,30}(?:around|near|rva)|globals? around.{0,20}rva|data region|inspect rva|data referenced by (?:this )?(?:region|code)|referenced data region",re.I),"INSPECT_DATA_REGION"),
 (re.compile(r"trace.{0,45}(?:return|returned)(?:.{0,35}(?:value|register|out.?parameter|out params?))?|return.?value trace|trace the return",re.I),"SH4_RETURN_VALUE_TRACE"),
 (re.compile(r"trace.{0,35}out.?parameter|out.?parameter trace|trace the return and out parameters",re.I),"SH4_OUT_PARAMETER_TRACE"),
 (re.compile(r"follow.{0,90}(?:returned )?(?:object )?(?:pointer|object)|object.?flow|object flow chain|trace all uses until",re.I),"SH4_OBJECT_FLOW_TRACE"),
 (re.compile(r"virtual method|vtable|function.?pointer call|indirect object call",re.I),"VTABLE_CALL_DETECTION"),
 (re.compile(r"object.?flow report|produce.{0,24}object[- ]flow",re.I),"OBJECT_FLOW_REPORT"),
 (re.compile(r"calling convention|abi model",re.I),"SH4_ABI_ANALYSIS"),
 (re.compile(r"call.?graph|callers?|callees?|direct calls?|reachable|досяжн|ланцюж.*виклик|внутрішн.*функц",re.I),"BUILD_CALL_GRAPH"),
 (re.compile(r"ordinal|import.?call|import caller|імпорт",re.I),"IMPORT_XREF"),
 (re.compile(r"string.?xref|string references?|strings?.{0,60}referenced by.{0,30}(?:region|code)|data.{0,30}referenced by.{0,30}region|рядк",re.I),"STRING_XREF"),
 (re.compile(r"data.?xref|data references?\b|посилан.*дан",re.I),"DATA_XREF"),
 (re.compile(r"search.{0,70}(?:ascii|utf.?16|strings?)|identify.{0,120}(?:process|service|class|interface|guid|clsid|ipc endpoint)|search targets?.{0,40}(?:process|service|guid|clsid)",re.I),"SEARCH_STRINGS"),
 (re.compile(r"\.RD|\.FEA|\.MP0|\.RL\b|\.RT\b|\.MG[1-3]|\.CTY?|\.CNY|\.PDX|\.STT|\.TYP|ZONE\.CFG|extensions?|map family|native map",re.I),"SEARCH_EXTENSIONS"),
 (re.compile(r"rank|candidate|behavior|behaviour|score|buffer|file.?like|path.?like|класифік|рейтинг|кандидат|поведінк|особливо шукати функц",re.I),"RANK_FUNCTIONS"),
 (re.compile(r"disassembl|instruction|basic block|extract|дизасемб|інструкц",re.I),"SH4_DISASSEMBLE"),
 (re.compile(r"\bPE_ANALYZE\b|PE import table|analyze pe imports",re.I),"PE_ANALYZE"),
]
CONSTRAINT_RE=re.compile(r"^(?:do not|don't|never|must not|не |не\s+|заборон|без\s+|avoid\b|respect\b|preserve\b|only include\b|do not force\b)",re.I)
INTERPRETATION_RE=re.compile(r"^(?:do not guess|don't guess|do not invent|do not assume|don't assume|only include links supported|do not force a classification|binary raw search is authoritative|but binary raw search is authoritative|semantic evidence only|не вгадувати|не вигадувати семантичні назви)",re.I)

def classify_instruction(text):
    """Return an instruction class before mapping only actionable operations."""
    s=re.sub(r"^\s*\d+[.)]\s*","",str(text)).strip()
    if not s:return "CONSTRAINT"
    if INTERPRETATION_RE.search(s):return "INTERPRETATION_RULE"
    if re.search(r"neutral names|no semantic names|sub_[0-9a-f]{4,8}|without semantic labels|нейтральн.{0,20}назв",s,re.I):return "INTERPRETATION_RULE"
    if CONSTRAINT_RE.search(s) or re.search(r"\brespect SH4 delay slots\b|\bdo not analyze NK\.BIN\b",s,re.I):return "CONSTRAINT"
    if re.search(r"\b(?:must contain|provide|show|include|format as|for every (?:hit|match|GUID).{0,30}record|GUID relationship table|record:)\b",s,re.I):return "OUTPUT_REQUIREMENT"
    return "OPERATION"

def _normalize_method_block(raw):
    """Join visual wraps while keeping explicit list/colon boundaries visible."""
    lines=[]
    for raw_line in str(raw).splitlines():
        line=raw_line.strip()
        if not line: continue
        line=re.sub(r"^(?:\d+[.)]|[-*•])\s*","",line).strip()
        if not line: continue
        is_list=bool(re.match(r"^(?:[-*•]|\d+[.)])\s+",raw_line.strip()))
        if lines and not is_list and not lines[-1].endswith((".","!","?",":",";")):
            lines[-1]+=" "+line
        else:
            lines.append(line)
    return "\n".join(lines)

def _method_fragments(raw):
    """Return human-readable fragments with semantic roles for diagnostics."""
    normalized=_normalize_method_block(raw)
    rows=[];colon_role=None;classification_parent=False
    for source in str(raw).splitlines():
        s=source.strip()
        if not s: continue
        numbered=bool(re.match(r"^\d+[.)]\s+",s))
        listed=bool(re.match(r"^[-*•]\s+",s))
        s=re.sub(r"^(?:\d+[.)]|[-*•])\s*","",s).strip()
        if not s:continue
        if INTERPRETATION_RE.search(s) or re.search(r"do not force a classification|do not guess|do not assume",s,re.I): role="INTERPRETATION_RULE"
        elif classify_instruction(s)=="CONSTRAINT": role="CONSTRAINT"
        elif re.match(r"^(?:stop when|stop after|until|at least until)\b",s,re.I): role="STOP_CONDITION"
        elif re.match(r"^if it is stored\b",s,re.I): role="PARAMETER"
        elif re.match(r"^(?:(?:for every (?:hit|match|GUID).{0,30}record)|(?:for every argument )?provide|build a GUID relationship table|trace at least)\s*:?$",s,re.I): role="OUTPUT_FIELD"
        elif colon_role and (listed or not numbered): role=colon_role
        elif numbered or not rows or re.match(r"^(?:also\s+)?(?:inspect|export|read|trace|follow|determine|identify|recover|analy[sz]e)\b",s,re.I): role="OPERATION"
        else: role="SUBITEM"
        if role=="OPERATION" and re.search(r"(?:determine whether it is|determine whether (?:it|the GUID) is used as)\s*:?$",s,re.I):
            classification_parent=True;colon_role="CLASSIFICATION_OPTION"
        elif role=="OPERATION" and re.search(r"determine\s*:$",s,re.I):
            colon_role="OUTPUT_FIELD"
        elif role=="OPERATION" and s.endswith(":"):
            colon_role="OUTPUT_FIELD" if re.search(r"provide|report|include|return",s,re.I) else "PARAMETER"
        elif role=="OUTPUT_FIELD" and s.endswith(":"):
            colon_role="OUTPUT_FIELD"
        elif role=="OUTPUT_FIELD":
            colon_role="OUTPUT_FIELD"
        elif role=="PARAMETER" and s.endswith(":"):
            colon_role="PARAMETER"
        elif role in ("CLASSIFICATION_OPTION","OUTPUT_FIELD","PARAMETER") and not s.endswith(":"):
            pass
        elif not s.endswith(":") and role=="OPERATION":
            colon_role=None;classification_parent=False
        rows.append({"text":s,"role":role})
    if not rows and normalized:rows=[{"text":normalized,"role":"OPERATION"}]
    return normalized,rows

def _operations_for_method(normalized,fragments):
    """Compile one semantic block; list values and output fields remain data."""
    semantic=" ".join(x["text"] for x in fragments if x["role"] in ("OPERATION","SUBITEM"))
    selected=[]
    for rule_index,(pattern,operation) in enumerate(METHOD_RULES):
        if (pattern.search(semantic) or (rule_index<11 and pattern.search(normalized))) and operation not in selected:selected.append(operation)
    if re.search(r"search all available.{0,180}(?:EXE.{0,100}HEX|firmware/update)",normalized,re.I|re.S):
        selected.extend(["MULTI_ARTIFACT_SCOPE","CORPUS_BINARY_PATTERN_SEARCH"])
    if re.search(r"if (?:a module other than NAVIMAIN|another module) contains GUID[_ -]A.{0,120}(?:GUID[_ -]D)?.{0,180}focused SH4 analysis",normalized,re.I|re.S):
        selected=[op for op in selected if op not in {"CORPUS_CODE_XREF_ANALYSIS","BUILD_CALL_GRAPH","VTABLE_CALL_DETECTION"}]
        selected.extend(["CONDITIONAL_FOCUSED_ANALYSIS","SH4_DISASSEMBLE","SH4_XREF_ANALYSIS","STRING_XREF","IMPORT_XREF"])
    if "CONDITIONAL_FOCUSED_ANALYSIS" in selected:
        selected.extend(["SH4_DISASSEMBLE","SH4_XREF_ANALYSIS","STRING_XREF","IMPORT_XREF"])
    if re.search(r"csv|\.csv",semantic,re.I):selected.append("EXPORT_CSV")
    if re.search(r"report|зві(т|ту)|summary|package|zip|stop condition|заверш",semantic,re.I):selected.append("GENERATE_REPORT")
    if re.search(r"inspect.{0,50}rva|data region|data referenced by (?:this )?region",semantic,re.I):selected.append("INSPECT_DATA_REGION")
    if re.search(r"(?:inspect.{0,80}rva|data region).{0,240}(?:bytes around|export|read)",normalized,re.I):selected.append("READ_RVA_BYTES")
    if re.search(r"determine whether (?:it|the GUID) is used",normalized,re.I) and re.search(r"\bguid\b",normalized,re.I):
        if "CORPUS_CODE_XREF_ANALYSIS" not in selected:selected.append("CORPUS_CODE_XREF_ANALYSIS")
    if re.search(r"determine whether it is\s*:?",normalized,re.I) and re.search(r"\bGUID\b",normalized,re.I):
        if "WINDOWS_GUID_INTERPRET" not in selected:selected.append("WINDOWS_GUID_INTERPRET")
    if re.search(r"inspect.{0,50}rva|data region",semantic,re.I) and re.search(r"\b(?:64|bytes|export)\b",normalized,re.I):selected.extend(["HEX_VIEW","ASCII_VIEW","UTF16LE_VIEW"])
    if re.search(r"(?:hex|ascii|utf.?16le)",normalized,re.I) and re.search(r"(?:rva|bytes|data region)",normalized,re.I) and re.search(r"(?:hex.{0,25}ascii|ascii.{0,25}utf.?16|utf.?16le view)",normalized,re.I):selected.extend(["HEX_VIEW","ASCII_VIEW","UTF16LE_VIEW"])
    if re.search(r"trace.{0,35}(?:return|out)|return and out parameters",semantic,re.I):selected.extend(["SH4_RETURN_VALUE_TRACE","SH4_OUT_PARAMETER_TRACE"])
    if "SEARCH_STRINGS" in selected and re.search(r"data referenced by (?:this )?(?:region|code)",semantic,re.I) and not re.search(r"data\s+xrefs?|data references?\b",semantic,re.I):
        selected=[op for op in selected if op!="DATA_XREF"]
    if "SEARCH_STRINGS" in selected and "STRING_XREF" in selected:
        priority=["SEARCH_STRINGS","STRING_XREF","INSPECT_DATA_REGION"]
        selected=sorted(dict.fromkeys(selected),key=lambda op:priority.index(op) if op in priority else len(priority))
    if "CORPUS_CODE_XREF_ANALYSIS" in selected:
        selected=[op for op in selected if op!="DATA_XREF"]
    if "RANK_ARTIFACTS" in selected:
        selected=[op for op in selected if op not in {"RANK_FUNCTIONS","VTABLE_CALL_DETECTION"}]
    return list(dict.fromkeys(selected)),semantic

def _expand_conditional_operations(normalized,selected):
    if "CORPUS_CODE_XREF_ANALYSIS" in selected and re.search(r"\bif\b.{0,160}\bthen\b",normalized,re.I):
        return list(dict.fromkeys([x for x in selected if x!="CORPUS_CODE_XREF_ANALYSIS"]+["SH4_DISASSEMBLE","SH4_XREF","IMPORT_XREF","STRING_XREF"]))
    return selected

def _artifact_scope(text):
    s=str(text)
    if re.search(r"firmware/update (?:corpus|files|artifacts)|all available.{0,100}firmware/update",s,re.I|re.S):return {"kind":"firmware"}
    if re.search(r"all\s+(?:cataloged\s+)?PE(?:32)?\s+files?",s,re.I):return {"kind":"pe"}
    if re.search(r"all\s+(?:cataloged\s+)?firmware(?:/update)?\s+artifacts?",s,re.I):return {"kind":"firmware"}
    folder=re.search(r"(?:folder|directory|corpus)\s*[:=]?\s*[`\"']([^`\"']+)[`\"']",s,re.I)
    if folder:return {"kind":"folder","path":folder.group(1)}
    corpus=re.search(r"(?:corpus|source_type|artifact_id)\s*(?:name|id)?\s*[:=]\s*([^\n.;,]+)",s,re.I)
    if corpus:return {"kind":"corpus","name":corpus.group(1).strip().strip("`\"'")}
    classes=re.search(r"artifact classes?\s*[:=]\s*([^\n.;]+)",s,re.I)
    if classes:return {"kind":"classes","values":[x.strip().lower().lstrip(".") for x in re.split(r"[,/|]",classes.group(1)) if x.strip()]}
    if re.search(r"all\s+(?:cataloged\s+)?artifacts?|whole corpus|entire corpus|corpus-wide|across the corpus",s,re.I):return {"kind":"all_corpus"}
    return {"kind":"all_corpus"}

def _file_type_filters(text):
    found=re.findall(r"\.?\b(EXE|DLL|BIN|DAT|ABS|HEX|IMG|ROM|FW|UPD)\b",str(text),re.I)
    return list(dict.fromkeys(x.upper() for x in found))

def _catalog_artifacts(root,scope=None,file_types=None):
    scope=scope or {"kind":"all_corpus"};kind=scope.get("kind","all_corpus");root=Path(root).resolve()
    db=root/"research"/"db_lab"/"analysis.sqlite"
    if not db.is_file():return [],[{"reason":"ARTIFACT_CATALOG_MISSING","path":str(db)}]
    conn=sqlite3.connect(f"file:{db}?mode=ro",uri=True);conn.row_factory=sqlite3.Row
    try:
        rows=[dict(x) for x in conn.execute("SELECT f.file_id,f.artifact_id,f.source_path,f.relative_path,f.filename,f.size,f.sha256 AS file_sha256,f.file_type,f.format_candidate,f.artifact_role AS file_role,f.source_offset,f.container_artifact,f.is_directory,a.source_type,a.source_path AS artifact_path,a.sha256 AS artifact_sha256,a.artifact_role AS artifact_role,a.magic FROM files f LEFT JOIN artifacts a ON a.artifact_id=f.artifact_id WHERE COALESCE(f.is_directory,0)=0 ORDER BY f.source_path")]
    finally:conn.close()
    allowed={str(x).lower().lstrip(".") for x in (file_types or scope.get("extensions") or [])};selected=[];missing=[]
    named={str(x).casefold() for x in scope.get("artifacts",[])}
    for item in rows:
        path=Path(item["source_path"]).expanduser()
        ext=(item.get("file_type") or path.suffix.lstrip(".") or "binary").lower()
        role=(item.get("file_role") or item.get("artifact_role") or "").lower();source_type=(item.get("source_type") or "").lower()
        excluded={str(x).casefold() for x in scope.get("exclude_filenames",[])}
        if path.name.casefold() in excluded:continue
        if named and path.name.casefold() not in named:continue
        if allowed and ext not in allowed and path.suffix.lower().lstrip(".") not in allowed:continue
        if kind=="pe" and ext not in {"exe","dll","ocx","sys","pe"} and "executable" not in role and "MZ" not in str(item.get("magic") or "").upper() and "PE" not in str(item.get("format_candidate") or "").upper():continue
        if kind=="firmware" and not (ext in {"exe","dll","bin","dat","abs","hex","img","rom","fw","upd","iso","cab"} or "firmware" in role or "firmware" in source_type or "disc" in source_type):continue
        if kind=="folder":
            folder=Path(scope.get("path",".")).expanduser();folder=(root/folder).resolve() if not folder.is_absolute() else folder.resolve()
            try:path.resolve().relative_to(folder)
            except (ValueError,OSError):continue
        if kind=="classes":
            classes={str(x).lower().lstrip(".") for x in scope.get("values",[])}
            if ext not in classes and role not in classes:continue
        if kind=="corpus":
            name=str(scope.get("name","")).casefold()
            haystack=" ".join(str(item.get(k) or "") for k in ("artifact_id","source_type","relative_path","container_artifact","artifact_path")).casefold()
            if not name or name not in haystack:continue
        if path.is_file():selected.append(item)
        else:missing.append({"path":str(path),"artifact_id":item.get("artifact_id"),"reason":"CATALOGED_SOURCE_UNAVAILABLE"})
    return selected,missing

def _scan_patterns(path,patterns,chunk_size=4*1024*1024):
    """Stream a file once, hash it, and record exact byte-pattern offsets."""
    patterns=[(str(pid),bytes(raw)) for pid,raw in patterns if raw]
    offsets={pid:set() for pid,_ in patterns};digest=hashlib.sha256();maxlen=max((len(x[1]) for x in patterns),default=1);carry=b"";position=0
    with Path(path).open("rb") as f:
        while True:
            chunk=f.read(chunk_size)
            if not chunk:break
            digest.update(chunk);data=carry+chunk;base=position-len(carry)
            for pid,needle in patterns:
                start=0
                while True:
                    found=data.find(needle,start)
                    if found<0:break
                    absolute=base+found
                    if absolute>=0 and absolute<position+len(chunk):offsets[pid].add(absolute)
                    start=found+1
            position+=len(chunk);carry=data[-(maxlen-1):] if maxlen>1 else b""
    hits=[]
    for pid,needle in patterns:
        for occurrence,offset in enumerate(sorted(offsets[pid]),1):hits.append({"pattern_id":pid,"file_offset":offset,"occurrence_index":occurrence,"pattern_length":len(needle)})
    return digest.hexdigest(),sorted(hits,key=lambda x:(x["file_offset"],x["pattern_id"]))

def _corpus_pattern_specs(task,requested_ids=None,explicit=None):
    specs={}
    for row in explicit or []:
        if not isinstance(row,dict):continue
        pid=str(row.get("pattern_id") or row.get("id") or f"PATTERN_{len(specs)+1}")
        raw=row.get("raw_hex") or row.get("hex")
        try:specs[pid]={"raw":bytes.fromhex(re.sub(r"[^0-9a-f]","",str(raw),flags=re.I)),"canonical":row.get("canonical_text") or row.get("guid")}
        except ValueError:continue
    all_text="\n".join(str(x) for field in ("known_facts","methods","expected_outputs") for x in task.get(field,[]))
    uuid_rx=r"(?<![0-9A-Fa-f])[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}(?![0-9A-Fa-f])"
    for match in re.finditer(uuid_rx,all_text):
        canonical=match.group(0);prefix=all_text[max(0,match.start()-64):match.start()]
        names=re.findall(GUID_LABEL_RE,prefix,re.I);pid=names[-1].replace("-","_").replace(" ","_").upper() if names else "GUID_"+canonical[:8].upper()
        try:specs.setdefault(pid,{"raw":uuid.UUID(canonical).bytes_le,"canonical":canonical})
        except ValueError:pass
    for m in re.finditer(r"\b(GUID[_ -][A-Z0-9]{1,3})\s*[:=]\s*(?:0x)?([0-9A-Fa-f]{32})\b",all_text,re.I):
        try:specs[m.group(1).replace("-","_").upper()]={"raw":bytes.fromhex(m.group(2)),"canonical":None}
        except ValueError:pass
    ids={str(x).replace("-","_").upper() for x in requested_ids or []}
    return {k:v for k,v in specs.items() if not ids or k in ids}

def _find_text_occurrences(path,terms,encodings):
    patterns=[]
    for term in terms:
        for encoding in encodings:
            try:raw=term.encode("ascii" if encoding.upper()=="ASCII" else "utf-16le")
            except UnicodeEncodeError:continue
            patterns.append((f"{term}|{encoding}",raw))
    _,hits=_scan_patterns(path,patterns)
    return [{"term":x["pattern_id"].rsplit("|",1)[0],"encoding":x["pattern_id"].rsplit("|",1)[1],"file_offset":x["file_offset"],"occurrence_index":x["occurrence_index"]} for x in hits]

CORPUS_IMPLEMENTATIONS={"cataloged raw-byte search","cataloged positive-control scan","validated PE section mapping","SH4 xrefs around catalog pattern hits","cataloged ASCII and UTF-16LE search","cataloged PE import/export symbol search","evidence relationship aggregation","weighted evidence ranking"}
CORPUS_OPERATIONS={op for op,row in OPERATION_REGISTRY.items() if row.get("implementation") in CORPUS_IMPLEMENTATIONS}
OPERATION_ALIASES={op:row["executor_operation"] for op,row in OPERATION_REGISTRY.items() if row.get("executor_operation")}
CORPUS_EXECUTED_OPERATIONS=set(CORPUS_OPERATIONS)

def validate_execution_plan(plan, capability_registry, available_capabilities):
    """Dry-run only: validate operation, scope, schema, dependencies and routes."""
    issues=[];names=[];route_exempt={"MULTI_ARTIFACT_SCOPE","CONDITIONAL_FOCUSED_ANALYSIS"}
    for index,item in enumerate(plan,1):
        if not isinstance(item,dict):issues.append({"step":index,"error":"STEP_NOT_OBJECT"});continue
        op=item.get("operation");names.append(op)
        if op not in OPERATION_REGISTRY:issues.append({"step":index,"operation":op,"error":"UNREGISTERED_OPERATION"});continue
        for field in ("parameters","artifact_scope","dependencies","output_schema","required_capabilities","executor_implementation"):
            if field not in item:issues.append({"step":index,"operation":op,"error":"MISSING_"+field.upper()})
        if item.get("required_capabilities")!=OPERATION_REGISTRY[op].get("capabilities",[]):issues.append({"step":index,"operation":op,"error":"CAPABILITY_BINDING_MISMATCH"})
        if item.get("executor_implementation")!=OPERATION_REGISTRY[op].get("implementation"):issues.append({"step":index,"operation":op,"error":"EXECUTOR_BINDING_MISMATCH"})
        if not OPERATION_REGISTRY[op].get("implementation"):
            issues.append({"step":index,"operation":op,"error":"MISSING_EXECUTOR_IMPLEMENTATION"})
        for cap in OPERATION_REGISTRY[op].get("capabilities",[]):
            if cap not in available_capabilities or capability_registry.get(cap,{}).get("status")=="UNSUPPORTED":issues.append({"step":index,"operation":op,"capability":cap,"error":"CAPABILITY_UNAVAILABLE"})
    return {"status":"PASS" if not issues else "FAIL","steps":len(plan),"unregistered_operations":sum(x.get("error")=="UNREGISTERED_OPERATION" for x in issues),"issues":issues,"operations":names}

def _run_corpus_operation(operation,ctx,params):
    from .artifact_lab.binary_analysis import pe_analyze,pe_file_offset_to_rva
    task=ctx["task"];scope=params.get("artifact_scope",{"kind":"all_corpus"});file_types=params.get("file_type_filters") or None
    if operation in ("CORPUS_BINARY_PATTERN_SEARCH","POSITIVE_CONTROL"):
        ids=params.get("pattern_ids",[]);explicit=params.get("patterns") or task.get("parameters",{}).get("patterns")
        specs=_corpus_pattern_specs(task,ids,explicit)
        if operation=="POSITIVE_CONTROL" and len(specs)<len(set(ids)):
            result={"status":"INCONCLUSIVE","valid":False,"missing_pattern_definitions":sorted(set(ids)-set(specs)),"control_artifact":params.get("control_artifact","NAVIMAIN.EXE"),"hits":[]}
            ctx["positive_control"]=result;ctx["halt_analysis"]=True;ctx["finding_status_override"]="INCONCLUSIVE"
            _save_json(ctx["run"]/"data"/"positive_control.json",result);return
        rows,missing=_catalog_artifacts(ctx["root"],scope,file_types)
        if operation=="POSITIVE_CONTROL":
            control=str(params.get("control_artifact","NAVIMAIN.EXE")).casefold()
            rows=[x for x in rows if Path(x["source_path"]).name.casefold()==Path(control).name.casefold()]
        binary_specs=[(pid,x["raw"]) for pid,x in specs.items()]
        text_specs=[]
        for pid,x in specs.items():
            if x.get("canonical"):
                for enc,codec in (("canonical_text_ascii","ascii"),("canonical_text_utf16le","utf-16le")):
                    try:text_specs.append((f"{pid}|{enc}",str(x["canonical"]).encode(codec)))
                    except UnicodeEncodeError:pass
        hits=[];pe_cache={};scanned=[]
        for item in rows:
            path=Path(item["source_path"]).expanduser();checksum,file_hits=_scan_patterns(path,binary_specs+text_specs)
            item.update({"current_sha256":checksum,"hash_matches_catalog":not item.get("file_sha256") or checksum==item.get("file_sha256")})
            scanned.append(item)
            is_pe=False;pe=None
            with path.open("rb") as f:signature=f.read(2)
            if signature==b"MZ":
                try:pe=pe_analyze(path.read_bytes());is_pe=bool(pe)
                except (OSError,MemoryError):pe=None
            for fh in file_hits:
                pid=fh["pattern_id"].split("|",1)[0];representation="raw_binary" if "|" not in fh["pattern_id"] else fh["pattern_id"].split("|",1)[1]
                provenance={"artifact_id":item.get("artifact_id"),"catalog_file_id":item.get("file_id"),"source_type":item.get("source_type"),"artifact_role":item.get("artifact_role") or item.get("file_role"),"relative_path":item.get("relative_path"),"container_artifact":item.get("container_artifact"),"cataloged_source_path":item.get("source_path"),"artifact_path":item.get("artifact_path"),"catalog_sha256":item.get("file_sha256"),"sha256":checksum,"hash_matches_catalog":item["hash_matches_catalog"]}
                hit={**fh,"pattern_id":pid,"representation":representation,"source_path":str(path.resolve()),"sha256":checksum,"file_type":item.get("file_type"),"is_pe":is_pe,"pe32":bool(pe and not pe.get("pe32_plus")),"pe_machine":pe.get("machine") if pe else None,"artifact_provenance":provenance,"source_file_offset":int(item.get("source_offset") or 0)+int(fh["file_offset"])}
                if is_pe and pe:
                    try:hit["pe_mapping"]=pe_file_offset_to_rva(pe,fh["file_offset"])
                    except ValueError:hit["pe_mapping"]=None
                hits.append(hit)
        if operation=="POSITIVE_CONTROL":
            required=set(ids);found={x["pattern_id"] for x in hits if x.get("representation")=="raw_binary"}
            result={"status":"PASS" if required and required.issubset(found) else "FAIL","valid":bool(required and required.issubset(found)),"control_artifact":params.get("control_artifact","NAVIMAIN.EXE"),"required_pattern_ids":sorted(required),"found_pattern_ids":sorted(found),"hits":[x for x in hits if x.get("representation")=="raw_binary"],"missing_catalog_artifacts":missing}
            ctx["positive_control"]=result
            if not result["valid"]:
                ctx["halt_analysis"]=True;ctx["finding_status_override"]="INVALID" if any(Path(x["source_path"]).name.casefold()==Path(result["control_artifact"]).name.casefold() for x in scanned) else "INCONCLUSIVE"
            _save_json(ctx["run"]/"data"/"positive_control.json",result)
        else:
            ctx["corpus_artifacts"]=scanned;ctx["corpus_pattern_hits"]=hits;ctx["catalog_missing_artifacts"]=missing
            _save_json(ctx["run"]/"data"/"corpus_binary_pattern_hits.json",{"pattern_count":len(specs),"scanned_artifact_count":len(scanned),"missing_catalog_artifacts":missing,"hits":hits})
        return
    if ctx.get("halt_analysis"):
        ctx.setdefault("skipped_operations",[]).append({"operation":operation,"reason":"POSITIVE_CONTROL_FAILED"});return
    if operation=="CORPUS_STRING_SEARCH":
        rows,missing=_catalog_artifacts(ctx["root"],scope,file_types)
        if params.get("scope_modules_matched_by_guid"):
            matched={Path(x["source_path"]).resolve() for x in ctx.get("corpus_pattern_hits",[]) if x.get("representation")=="raw_binary"}
            rows=[x for x in rows if Path(x["source_path"]).resolve() in matched]
        terms=params.get("terms") or re.findall(r"\b(NaviBase|Navi|Navigation|Map|Route|DB|Database|Reader|Loader|Manager|Service|Server|Client|Factory|CreateInstance|QueryInterface)\b","\n".join(map(str,task.get("methods",[]))),re.I)
        terms.extend(params.get("exact_strings",[]))
        if params.get("canonical_guid_secondary"):
            terms.extend(str(x.get("canonical")) for x in _corpus_pattern_specs(task,params.get("pattern_ids",[])).values() if x.get("canonical"))
        terms=list(dict.fromkeys(terms));encodings=params.get("encodings",["ASCII","UTF-16LE"]);results=[]
        for item in rows:
            path=Path(item["source_path"]);found=_find_text_occurrences(path,terms,encodings)
            if found:results.extend({**x,"artifact_id":item.get("artifact_id"),"source_path":str(path.resolve()),"file_type":item.get("file_type"),"artifact_provenance":{"source_type":item.get("source_type"),"artifact_role":item.get("artifact_role") or item.get("file_role"),"relative_path":item.get("relative_path"),"container_artifact":item.get("container_artifact"),"catalog_sha256":item.get("file_sha256")}} for x in found)
        ctx["corpus_string_hits"]=results;ctx["catalog_missing_artifacts"]=ctx.get("catalog_missing_artifacts",[])+missing
        _save_json(ctx["run"]/"data"/"corpus_string_hits.json",{"terms":terms,"encodings":encodings,"hits":results,"missing_catalog_artifacts":missing});return
    if operation=="CORPUS_SYMBOL_SEARCH":
        rows,missing=_catalog_artifacts(ctx["root"],{**scope,"kind":"pe"},file_types or ["exe","dll"]);terms=params.get("terms",[]);results=[]
        for item in rows:
            path=Path(item["source_path"]);data=path.read_bytes();pe=pe_analyze(data)
            if not pe:continue
            symbols=[]
            for imp in pe.get("import_records",[]):
                if imp.get("name"):symbols.append({"name":imp["name"],"kind":"import","dll":imp.get("dll"),"ordinal":imp.get("ordinal")})
            symbols.extend({"name":x,"kind":"export"} for x in pe.get("exports",[]) if x)
            for symbol in symbols:
                for term in terms:
                    if str(term).casefold() in symbol["name"].casefold():
                        try:decoded=__import__("research.db_lab.semantic_analysis",fromlist=["parse_msvc_decorated_symbol"]).parse_msvc_decorated_symbol(symbol["name"]) if symbol["name"].startswith("?") else None
                        except Exception:decoded=None
                        results.append({**symbol,"query":term,"decoded_msvc":decoded,"source_path":str(path.resolve()),"artifact_id":item.get("artifact_id"),"sha256":item.get("file_sha256")})
        ctx["corpus_symbol_hits"]=results;_save_json(ctx["run"]/"data"/"corpus_symbol_hits.json",{"terms":terms,"hits":results,"missing_catalog_artifacts":missing});return
    if operation=="PE_FILE_OFFSET_MAPPING":
        hits=params.get("_input_rows") if isinstance(params.get("_input_rows"),list) else ctx.get("corpus_pattern_hits",[]);mapped=[]
        if hits:
            for hit in hits:
                sh4_machines={0x1A6,0x1A3,0x1A2}
                eligible=hit.get("is_pe") and (not params.get("require_pe32_sh4") or (hit.get("pe32") and hit.get("pe_machine") in sh4_machines))
                if eligible:mapped.append({**hit,"mapping":hit.get("pe_mapping")})
        else:
            rows,missing=_catalog_artifacts(ctx["root"],{**scope,"kind":"pe"},file_types);offsets=params.get("file_offsets",[])
            for item in rows:
                data=Path(item["source_path"]).read_bytes();pe=pe_analyze(data)
                if not pe:continue
                for offset in offsets:
                    try:mapped.append({"source_path":item["source_path"],"file_offset":int(offset),"mapping":pe_file_offset_to_rva(pe,offset)})
                    except ValueError:continue
        ctx["pe_offset_mappings"]=mapped;_save_json(ctx["run"]/"data"/"pe_offset_mappings.json",{"mappings":mapped});return
    if operation=="CORPUS_CODE_XREF_ANALYSIS":
        from .sh4_analysis import disassemble_module
        hits=ctx.get("corpus_pattern_hits",[]);analyses=[];seen=set()
        for hit in hits:
            mapping=hit.get("pe_mapping")
            if not hit.get("is_pe") or not mapping or (hit["source_path"],mapping["rva"]) in seen:continue
            seen.add((hit["source_path"],mapping["rva"]));analysis=disassemble_module(hit["source_path"])
            if analysis.get("status")!="SUPPORTED":analyses.append({"source_path":hit["source_path"],"pattern_id":hit["pattern_id"],"status":analysis.get("status"),"hit_rva":mapping["rva"]});continue
            rva=int(mapping["rva"]);xrefs=[x for x in analysis.get("normalized_xrefs",[]) if x.get("target_rva") is not None and abs(int(x["target_rva"])-rva)<16]
            functions={x.get("function_rva") for x in xrefs if x.get("function_rva") is not None};calls=[x for x in analysis.get("normalized_xrefs",[]) if x.get("xref_type")=="CALL" and any(f is not None and abs(int(x.get("instruction_rva",0))-int(f))<0x100 for f in functions)]
            nearby_strings=[x for x in analysis.get("strings",[]) if any(f is not None and abs(int(x.get("rva",0))-int(f))<0x100 for f in functions)]
            code_use=[x for x in xrefs if x.get("function_rva") is not None]
            indirect_calls=[x for x in analysis.get("indirect_call_xrefs",[]) if x.get("caller_function_rva") in functions]
            analyses.append({"source_path":hit["source_path"],"artifact_id":hit.get("artifact_provenance",{}).get("artifact_id"),"pattern_id":hit["pattern_id"],"hit_rva":rva,"status":"SUPPORTED","code_xrefs":[x for x in xrefs if x.get("xref_type") in ("CALL","BRANCH")],"data_xrefs":[x for x in xrefs if x.get("xref_type")=="DATA"],"code_use_xrefs":code_use,"referencing_functions":sorted(functions),"nearby_calls":calls,"indirect_calls":indirect_calls,"nearby_strings":nearby_strings,"xrefs":xrefs})
        ctx["corpus_code_xrefs"]=analyses;_save_json(ctx["run"]/"data"/"corpus_code_xrefs.json",{"analyses":analyses});return
    if operation=="BUILD_RELATIONSHIP_TABLE":
        hits=ctx.get("corpus_pattern_hits",[]);xrefs=ctx.get("corpus_code_xrefs",[]);strings=ctx.get("corpus_string_hits",[]);symbols=ctx.get("corpus_symbol_hits",[]);groups={}
        for hit in hits:
            pid=hit["pattern_id"];g=groups.setdefault(pid,{"pattern_id":pid,"canonical_guid":_corpus_pattern_specs(task,[pid]).get(pid,{}).get("canonical"),"files":set(),"modules":set(),"occurrence_count":0,"raw_hit_count":0,"xref_count":0,"code_use_count":0,"related_strings":[],"related_symbols":[],"classification":"UNKNOWN","confidence":"LOW: raw-byte presence only"})
            g["files"].add(hit["source_path"]);g["modules"].add(Path(hit["source_path"]).name);g["occurrence_count"]+=1
            if hit.get("representation")=="raw_binary":g["raw_hit_count"]+=1
        for pid,g in groups.items():
            for row in xrefs:
                if row.get("pattern_id")==pid and row.get("status")=="SUPPORTED":
                    g["xref_count"]+=len(row.get("xrefs",[]));g["code_use_count"]+=len(row.get("code_use_xrefs",[]))
            g["related_strings"]=[x for x in strings if Path(x.get("source_path","")).name in g["modules"]]
            g["related_symbols"]=[x for x in symbols if Path(x.get("source_path","")).name in g["modules"]]
            if g["code_use_count"]:g.update({"classification":"GUID_CANDIDATE_WITH_CODE_USE","confidence":"HIGH: code xrefs link to mapped GUID bytes"})
            elif g["xref_count"]:g.update({"classification":"GUID_CANDIDATE_WITH_XREFS","confidence":"MEDIUM: static xrefs reach mapped GUID bytes"})
            g["files"]=sorted(g["files"]);g["modules"]=sorted(g["modules"])
        ctx["relationship_table"]=list(groups.values());_save_json(ctx["run"]/"data"/"relationship_table.json",ctx["relationship_table"]);return
    if operation=="RANK_ARTIFACTS":
        weights=params.get("weights",{});scores={};
        def add(path,points,kind,evidence):
            row=scores.setdefault(path,{"source_path":path,"score":0,"evidence":[]});row["score"]+=int(points);row["evidence"].append({"rule":kind,"weight":int(points),"evidence":evidence})
        for hit in ctx.get("corpus_pattern_hits",[]):add(hit["source_path"],weights.get("raw_hit_without_xref",1),"raw_guid_hit",f"{hit['pattern_id']} at 0x{hit['file_offset']:X}")
        for row in ctx.get("corpus_code_xrefs",[]):
            if row.get("code_use_xrefs"):add(row["source_path"],weights.get("code_use",10),"guid_code_use",f"{len(row['code_use_xrefs'])} function-bounded xrefs reach the matched GUID bytes")
        for row in ctx.get("corpus_string_hits",[]):
            if "navibase" in row.get("term","").casefold():add(row["source_path"],weights.get("navibase_strings",8),"navibase_string",row["term"])
        for row in ctx.get("corpus_symbol_hits",[]):
            if any(x in row.get("name","").casefold() for x in ("navi","map","route","db","reader","manager","factory")):add(row["source_path"],weights.get("navigation_symbols",8),"navigation_symbol",row["name"])
            if any(x in row.get("name","").casefold() for x in ("factory","createinstance","register","queryinterface")):add(row["source_path"],weights.get("factory_registration",8),"factory_registration",row["name"])
        for row in ctx.get("corpus_code_xrefs",[]):
            behavior=row.get("indirect_calls",[])
            if behavior:add(row["source_path"],weights.get("object_vtable_behavior",8),"object_vtable_behavior",f"{len(behavior)} SH4 indirect calls in GUID-referencing functions; vtable role is a candidate, not proven")
        ctx["ranked_artifacts"]=sorted(scores.values(),key=lambda x:(-x["score"],x["source_path"]));_save_json(ctx["run"]/"data"/"ranked_artifacts.json",ctx["ranked_artifacts"]);return

def compile_operations(methods,expected_outputs,report_questions,stop_conditions):
    plan=[];unsupported=[];optional_unsupported=[];had_actionable=False
    for method_index,raw in enumerate(methods,1):
        instruction=str(raw).strip()
        if not instruction or instruction=="НЕ ВИЗНАЧЕНО":continue
        normalized,fragments=_method_fragments(instruction)
        if not normalized:continue
        selected,semantic=_operations_for_method(normalized,fragments)
        selected=_expand_conditional_operations(normalized,selected)
        if any(x["role"]=="OPERATION" for x in fragments):had_actionable=True
        if selected:plan.extend(selected)
        else:
            actionable=[x["text"] for x in fragments if x["role"]=="OPERATION"]
            if actionable:unsupported.append(normalized)
    outputs="\n".join(map(str,expected_outputs))
    for output in expected_outputs:
        for pattern,operation in METHOD_RULES:
            if pattern.search(str(output)):plan.append(operation)
    if re.search(r"\.csv\b",outputs,re.I):plan.append("EXPORT_CSV")
    if re.search(r"report|\.html|summary|зві",outputs,re.I) or report_questions or stop_conditions:plan.append("GENERATE_REPORT")
    if re.search(r"package|\.zip\b|архів",outputs,re.I):plan.append("PACKAGE_RESULTS")
    task_text="\n".join(map(str,methods))
    if "RANK_ARTIFACTS" in plan and not re.search(r"rank(?:ing)?\s+(?:candidate\s+)?functions?|function\s+ranking",task_text,re.I):
        plan=[op for op in plan if op!="RANK_FUNCTIONS"]
    plan=list(dict.fromkeys(plan))
    # A renderer request is executable output work; infer its required views.
    if any(re.search(r"hex.{0,40}ascii.{0,40}utf.?16|(?:provide|show|include).{0,40}(?:hex|ascii).{0,40}views?",_normalize_method_block(x),re.I) for x in methods+list(expected_outputs)):
        plan.extend(["HEX_VIEW","ASCII_VIEW","UTF16LE_VIEW"])
    plan=list(dict.fromkeys(plan))
    if any(x in plan for x in ("HEX_VIEW","ASCII_VIEW","UTF16LE_VIEW")):plan.append("READ_RVA_BYTES")
    if any(x in plan for x in ("READ_RVA_BYTES","INSPECT_DATA_REGION","WINDOWS_GUID_INTERPRET")): plan.append("PE_ANALYZE")
    if any(x in plan for x in ("SH4_CALL_ARGUMENT_TRACE","SH4_RETURN_VALUE_TRACE","SH4_OUT_PARAMETER_TRACE","SH4_OBJECT_FLOW_TRACE","VTABLE_CALL_DETECTION","INSPECT_DATA_REGION")):plan.append("SH4_DISASSEMBLE")
    plan=list(dict.fromkeys(plan))
    order=["POSITIVE_CONTROL_VALIDATION","MULTI_ARTIFACT_SCOPE","CORPUS_BINARY_PATTERN_SEARCH","PE_FILE_OFFSET_TO_RVA","CORPUS_CODE_XREF_ANALYSIS","CORPUS_STRING_SEARCH","CORPUS_SYMBOL_SEARCH","BUILD_RELATIONSHIP_TABLE","CONDITIONAL_FOCUSED_ANALYSIS","SH4_DISASSEMBLE","SH4_XREF_ANALYSIS","IMPORT_XREF","STRING_XREF","RANK_ARTIFACTS","PE_ANALYZE","SH4_XREF","BUILD_CALL_GRAPH","DATA_XREF","SEARCH_STRINGS","SEARCH_EXTENSIONS","SH4_ABI_ANALYSIS","MSVC_DECORATED_SYMBOL_PARSE","READ_RVA_BYTES","INSPECT_DATA_REGION","HEX_VIEW","ASCII_VIEW","UTF16LE_VIEW","SH4_CALL_ARGUMENT_TRACE","SH4_RETURN_VALUE_TRACE","SH4_OUT_PARAMETER_TRACE","SH4_OBJECT_FLOW_TRACE","VTABLE_CALL_DETECTION","WINDOWS_GUID_INTERPRET","OBJECT_FLOW_REPORT","EXPORT_CSV","GENERATE_REPORT","PACKAGE_RESULTS"]
    plan.sort(key=lambda x:order.index(x) if x in order else len(order))
    # Generic tasks without explicit artifact-analysis methods still need a registered analysis op.
    analysis_ops={op for op,row in OPERATION_REGISTRY.items() if row.get("implementation") not in {"find_readonly_artifact","csv.DictWriter","markdown_and_html_report","package_run","validated firmware/update corpus scope declaration","conditional SH4 evidence plan gate"}}
    if not any(x in plan for x in analysis_ops):
        if had_actionable and methods and methods!=["НЕ ВИЗНАЧЕНО"]:
            for raw in methods:
                normalized,fragments=_method_fragments(raw)
                if normalized and any(x["role"]=="OPERATION" for x in fragments):unsupported.append(normalized)
    # Preserve method scope and repeatable operation parameters in the saved
    # plan. Derived prerequisite/report operations have empty parameters.
    entries=[]
    for operation in plan:
        sources=[]
        for index,raw in enumerate(methods,1):
            normalized,fragments=_method_fragments(str(raw))
            selected,_=_operations_for_method(normalized,fragments) if normalized else ([],"")
            selected=_expand_conditional_operations(normalized,selected)
            if operation in selected:sources.append((index,str(raw)))
        if not sources: sources=[(None,"")]
        if operation in {"READ_RVA_BYTES","INSPECT_DATA_REGION","SH4_DISASSEMBLE","SH4_XREF","SH4_XREF_ANALYSIS","IMPORT_XREF","STRING_XREF","SH4_CALL_ARGUMENT_TRACE","SH4_RETURN_VALUE_TRACE","SH4_OUT_PARAMETER_TRACE","SH4_OBJECT_FLOW_TRACE","CORPUS_BINARY_PATTERN_SEARCH","POSITIVE_CONTROL","POSITIVE_CONTROL_VALIDATION","MULTI_ARTIFACT_SCOPE","PE_FILE_OFFSET_MAPPING","PE_FILE_OFFSET_TO_RVA","CORPUS_CODE_XREF_ANALYSIS","CORPUS_STRING_SEARCH","CORPUS_SYMBOL_SEARCH","BUILD_RELATIONSHIP_TABLE","CONDITIONAL_FOCUSED_ANALYSIS","RANK_ARTIFACTS"}:
            matched=[]
            for index,source in sources:
                values=[int(x,16) for x in re.findall(r"0x([0-9a-fA-F]{1,8})",source)]
                params={}
                if operation=="SH4_DISASSEMBLE" and len(values)>=2:
                    ranges=re.findall(r"RVA\s+(0x[0-9a-fA-F]+)\s*(?:-|to)\s*(0x[0-9a-fA-F]+)",source,re.I)
                    for lo,hi in ranges:matched.append({"operation":operation,"parameters":{"start_rva":int(lo,16),"end_rva":int(hi,16)},"source_method_item":index})
                    if not ranges:params={"start_rva":values[0],"end_rva":values[1]}
                elif operation in ("READ_RVA_BYTES","INSPECT_DATA_REGION") and values:
                    if operation=="READ_RVA_BYTES":
                        reads=re.findall(r"(\d+)\s+(?:raw\s+)?bytes?\s+(?:starting\s+)?(?:from|at)\s+(?:RVA\s+)?(0x[0-9a-fA-F]+)",source,re.I)
                        if reads:
                            for count,address in reads:matched.append({"operation":operation,"parameters":{"rva":int(address,16),"length":int(count)},"source_method_item":index})
                            continue
                        params["rva"]=values[-1] if len(values)>1 else values[0]
                        length=re.search(r"\b(\d+)\s+(?:raw\s+)?bytes?\b",source,re.I)
                        params["length"]=int(length.group(1)) if length else 64
                    else:
                        params["rva"]=values[0]
                        bm=re.search(r"before\s+(\d+).{0,20}after\s+(\d+)",source,re.I)
                        params.update({"before_bytes":int(bm.group(1)) if bm else 32,"after_bytes":int(bm.group(2)) if bm else 32})
                elif operation in ("SH4_CALL_ARGUMENT_TRACE","SH4_RETURN_VALUE_TRACE","SH4_OUT_PARAMETER_TRACE","SH4_OBJECT_FLOW_TRACE"):
                    cm=re.search(r"call[^\n]{0,60}?(0x[0-9a-fA-F]+)",source,re.I) or re.search(r"at\s+(?:RVA\s*)?(0x[0-9a-fA-F]+)",source,re.I)
                    if cm:params["call_rva"]=int(cm.group(1),16)
                    sym=re.search(r"\?[A-Za-z_?$][A-Za-z0-9_?$@]+",source)
                    if sym:params["decorated_symbol"]=sym.group(0).rstrip(".,;:")
                    loc=re.search(r"(?:argument|arg)\s*(?:location\s*)?(R[4-7]|stack\s*\+\s*0x[0-9a-f]+)",source,re.I)
                    if loc:params["argument_location"]=loc.group(1)
                elif operation in {"SH4_DISASSEMBLE","SH4_XREF","SH4_XREF_ANALYSIS","IMPORT_XREF","STRING_XREF"} and re.search(r"\bif\b.{0,260}(?:then|perform)",source,re.I|re.S):
                    params["artifact_scope"]=_artifact_scope(source);params["pattern_ids"]=list(dict.fromkeys(x.replace(" ","_").replace("-","_").upper() for x in re.findall(GUID_LABEL_RE,source,re.I)))
                    params["condition"]={"any_hit_pattern_ids":params["pattern_ids"],"artifact_excludes":["NAVIMAIN.EXE"]}
                elif operation in {"CORPUS_BINARY_PATTERN_SEARCH","POSITIVE_CONTROL","POSITIVE_CONTROL_VALIDATION","MULTI_ARTIFACT_SCOPE","PE_FILE_OFFSET_MAPPING","PE_FILE_OFFSET_TO_RVA","CORPUS_CODE_XREF_ANALYSIS","CORPUS_STRING_SEARCH","CORPUS_SYMBOL_SEARCH","BUILD_RELATIONSHIP_TABLE","CONDITIONAL_FOCUSED_ANALYSIS","RANK_ARTIFACTS"}:
                    params["artifact_scope"]=_artifact_scope(source)
                    params["file_type_filters"]=_file_type_filters(source)
                    if operation in {"CORPUS_BINARY_PATTERN_SEARCH","MULTI_ARTIFACT_SCOPE"}:params["include_non_pe"]=bool(re.search(r"do not limit.{0,30}PE|non.?PE",source,re.I))
                    ids=re.findall(GUID_LABEL_RE,source,re.I)
                    if ids:params["pattern_ids"]=list(dict.fromkeys(x.replace(" ","_").replace("-","_").upper() for x in ids))
                    if operation in {"POSITIVE_CONTROL","POSITIVE_CONTROL_VALIDATION"}:
                        name=re.search(r"([A-Za-z0-9_.-]+\.EXE)\s+(?:must|should)\s+contain",source,re.I)
                        params["control_artifact"]=name.group(1) if name else "NAVIMAIN.EXE"
                        if re.search(r"GUID[_ -]A",source,re.I) and re.search(r"GUID[_ -]D",source,re.I):params["pattern_ids"]=["GUID_A","GUID_D"]
                    if operation in ("CORPUS_STRING_SEARCH","CORPUS_SYMBOL_SEARCH"):
                        terms=re.findall(r"\b(NaviBase|Navi|Navigation|Map|Route|DB|Database|Reader|Loader|Manager|Service|Server|Client|Factory|CreateInstance|QueryInterface)\b",source,re.I)
                        params["terms"]=list(dict.fromkeys(terms))
                        params["substring_queries"]=params["terms"] if operation=="CORPUS_SYMBOL_SEARCH" else []
                        if operation=="CORPUS_STRING_SEARCH":
                            params["encodings"]=[x for x in ("ASCII","UTF-16LE") if re.search(x.replace("-","[- ]?") ,source,re.I)] or ["ASCII","UTF-16LE"]
                            params["scope_modules_matched_by_guid"]=bool(re.search(r"same modules|matching modules",source,re.I))
                            params["canonical_guid_secondary"]=bool(re.search(r"canonical GUID text forms?.{0,80}secondary",source,re.I))
                            params["exact_strings"]=list(dict.fromkeys(re.findall(r"(?<![0-9A-Fa-f])[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}(?![0-9A-Fa-f])",source)))
                            if params["canonical_guid_secondary"]:
                                params.update({"artifact_scope":{"kind":"firmware"},"priority":"SECONDARY"})
                    if operation=="PE_FILE_OFFSET_TO_RVA":params["require_pe32_sh4"]=True
                    if operation=="CORPUS_CODE_XREF_ANALYSIS" and re.search(r"\bif\b.{0,160}\bthen\b",source,re.I):
                        params["condition"]={"any_hit_pattern_ids":params.get("pattern_ids",[])}
                    if operation=="CORPUS_CODE_XREF_ANALYSIS":
                        _,frags=_method_fragments(source)
                        params["classification_options"]=[x["text"] for x in frags if x["role"]=="CLASSIFICATION_OPTION"]
                        params["do_not_force_classification"]=any(x["role"]=="INTERPRETATION_RULE" for x in frags)
                    if operation=="RANK_ARTIFACTS":
                        params["weights"]={"code_use":10,"factory_registration":8,"navibase_strings":8,"navigation_symbols":8,"object_vtable_behavior":8,"raw_hit_without_xref":1}
                    if operation=="CONDITIONAL_FOCUSED_ANALYSIS":params.update({"condition":{"artifact_excludes":["NAVIMAIN.EXE"],"any_hit_pattern_ids":["GUID_A","GUID_D"]},"actions":["SH4_DISASSEMBLE","SH4_XREF_ANALYSIS","STRING_XREF","IMPORT_XREF"],"requested_evidence":["caller","callee","factory/registration usage","nearby object/vtable operations"]})
                if not (operation=="SH4_DISASSEMBLE" and len(values)>=2 and re.search(r"RVA\s+0x[0-9a-fA-F]+\s*(?:-|to)\s*0x[0-9a-fA-F]+",source,re.I)):
                    matched.append({"operation":operation,"parameters":params,"source_method_item":index})
            entries.extend(matched)
        else: entries.append({"operation":operation,"parameters":{},"source_method_item":sources[0][0]})
    # Respect corpus exclusions as scoped parameters. Raw pattern reporting may
    # include NK.BIN when the pasted task expressly permits ordinary byte hits.
    all_method_text="\n".join(map(str,methods))
    if re.search(r"do not analyze NK\.BIN.{0,100}except.{0,80}(?:raw[- ]byte|byte[- ]hit|pattern hit)",all_method_text,re.I):
        for item in entries:
            if item.get("operation")=="CORPUS_BINARY_PATTERN_SEARCH":continue
            scope=item.setdefault("parameters",{}).setdefault("artifact_scope",{"kind":"all_corpus"})
            scope.setdefault("exclude_filenames",[]).append("NK.BIN")
            scope["exclude_filenames"]=list(dict.fromkeys(scope["exclude_filenames"]))
    # Remove only exact duplicate entries, never distinct RVAs or method items.
    unique=[];seen=set()
    for item in entries:
        key=(item["operation"],json.dumps(item["parameters"],sort_keys=True),item["source_method_item"])
        if key not in seen:unique.append(item);seen.add(key)
    return unique,list(dict.fromkeys(unsupported)),optional_unsupported

def annotate_execution_plan(plan,methods):
    """Attach scope, dependencies and requested output fields for preview/run validation."""
    unique=[dict(x) for x in plan]
    related=[x for x in unique if x["operation"]=="BUILD_RELATIONSHIP_TABLE"]
    if len(related)>1:
        primary=related[0]
        for extra in related[1:]:
            primary["parameters"]=dict(primary.get("parameters",{}))
            primary["parameters"]["pattern_ids"]=list(dict.fromkeys(primary["parameters"].get("pattern_ids",[])+extra.get("parameters",{}).get("pattern_ids",[])))
            unique.remove(extra)
    for item in unique:
        item.setdefault("artifact_scope",item.get("parameters",{}).get("artifact_scope"))
        item.setdefault("dependencies",[])
        item.setdefault("output_schema",[])
        item["required_capabilities"]=list(OPERATION_REGISTRY[item["operation"]].get("capabilities",[]))
        item["executor_implementation"]=OPERATION_REGISTRY[item["operation"]].get("implementation")
        if item["operation"]=="CORPUS_BINARY_PATTERN_SEARCH":
            item["parameters"].setdefault("include_non_pe",True)
            fields=[]
            for raw in methods:
                if re.search(r"for every hit record",str(raw),re.I):
                    _,frags=_method_fragments(str(raw));fields.extend(x["text"] for x in frags if x["role"]=="OUTPUT_FIELD" and x["text"].rstrip(":").casefold() not in {"for every hit record","record"})
            item["output_schema"]=list(dict.fromkeys(fields))
        if item["operation"]=="BUILD_RELATIONSHIP_TABLE":
            fields=[]
            for raw in methods:
                if re.search(r"build a GUID relationship table",str(raw),re.I):
                    _,frags=_method_fragments(str(raw));fields.extend(x["text"] for x in frags if x["role"]=="OUTPUT_FIELD" and x["text"].rstrip(":").casefold()!="build a guid relationship table")
            item["output_schema"]=list(dict.fromkeys(fields))
        if item["operation"]=="PE_FILE_OFFSET_TO_RVA":item["output_schema"]=["section","RVA","VA"]
        if item["operation"]=="CONDITIONAL_FOCUSED_ANALYSIS":
            evidence=["caller","callee","factory/registration usage","nearby object/vtable operations"]
            item["parameters"].update({"condition":{"artifact_excludes":["NAVIMAIN.EXE"],"any_hit_pattern_ids":["GUID_A","GUID_D"]},"actions":["SH4_DISASSEMBLE","SH4_XREF_ANALYSIS","STRING_XREF","IMPORT_XREF"],"requested_evidence":evidence})
            item["output_schema"]=evidence
        item["artifact_scope"]=item.get("parameters",{}).get("artifact_scope")
    prior=[]
    for item in unique:
        op=item["operation"]
        if op not in {"GENERATE_REPORT","PACKAGE_RESULTS"}:
            item["dependencies"]=list(prior)
            prior.append(op)
    return unique

def compile_diagnostics(methods,plan,unsupported,missing_capabilities=()):
    """Block-level compiler evidence, suitable for a saved task debug record."""
    from .tasks import CAPABILITY_REGISTRY,AVAILABLE_CAPABILITIES
    diagnostics=[]
    for method_index,raw in enumerate(methods,1):
        if not raw or raw=="НЕ ВИЗНАЧЕНО":continue
        normalized,fragments=_method_fragments(raw)
        selected,semantic=_operations_for_method(normalized,fragments)
        selected=_expand_conditional_operations(normalized,selected)
        plan_names=[x.get("operation") if isinstance(x,dict) else x for x in plan]
        operations=[op for op in selected if op in plan_names]
        operation_entries=[x for x in plan if isinstance(x,dict) and x.get("source_method_item")==method_index]
        caps=list(dict.fromkeys(cap for op in operations for cap in OPERATION_REGISTRY.get(op,{}).get("capabilities",[])))
        params={}
        end=re.search(r"until at least\s+(?:RVA\s*)?(0x[0-9a-f]+|\d+)",normalized,re.I)
        if end:params["end_rva"]=int(end.group(1),0)
        if re.search(r"createinstance",normalized,re.I) and "SH4_OBJECT_FLOW_TRACE" in operations:params["start"]="CreateInstance returned/out object"
        if re.search(r"register/global/local",normalized,re.I):params["track"]=["register","global","local"]
        if re.search(r"\b64\s+bytes?\b",normalized,re.I):params["length_bytes"]=64
        rva=re.search(r"\bRVA\s+(0x[0-9a-f]+|\d+)\b",normalized,re.I)
        if rva:params["rva"]=int(rva.group(1),0)
        call_rva=re.search(r"call\s+(?:at\s+)?(?:RVA\s+)?(0x[0-9a-f]+|\d+)",normalized,re.I)
        if call_rva and "SH4_CALL_ARGUMENT_TRACE" in operations:params["call_rva"]=int(call_rva.group(1),0)
        if "SH4_CALL_ARGUMENT_TRACE" in operations:
            regs=sorted({int(x) for x in re.findall(r"\bR([4-7])\b",normalized,re.I)})
            params["recover_registers"]=[f"R{x}" for x in regs or range(4,8)]
            params["include_stack_arguments"]=bool(re.search(r"stack[- ](?:passed|arguments?|parameters?)|stack\b",normalized,re.I))
            fields=[]
            for pattern,name in ((r"\blocation\b","location"),(r"\bvalue\b","value"),(r"source instruction|instruction source","source_instruction"),(r"literal[- ]pool source|source.{0,15}literal pool","literal_pool_source"),(r"resolved\s+rva\s*/\s*va|resolved rva/va","resolved_rva_va"),(r"\bconfidence\b","confidence")):
                if re.search(pattern,normalized,re.I):fields.append(name)
            if fields:params["requested_output_fields"]=fields
        if "SEARCH_STRINGS" in operations:
            target_patterns=((r"process name","process_name"),(r"service name","service_name"),(r"class name","class_name"),(r"interface name","interface_name"),(r"\bGUID\b","GUID"),(r"CLSID[- ]like value","CLSID_like_value"),(r"IPC endpoint","IPC_endpoint"))
            params["search_targets"]=[name for pattern,name in target_patterns if re.search(pattern,normalized,re.I)]
            encodings=[]
            if re.search(r"ASCII",normalized,re.I):encodings.append("ASCII")
            if re.search(r"UTF[- ]?16(?:LE)?",normalized,re.I):encodings.append("UTF-16LE")
            if encodings:params["encodings"]=encodings
            if re.search(r"referenced by (?:this )?region|region.{0,25}referenced data",normalized,re.I):params["scope"]="data/code referenced by the analyzed region"
        for frag in fragments:
            if frag["role"] in ("CLASSIFICATION_OPTION","OUTPUT_FIELD","PARAMETER"):
                params.setdefault(frag["role"].lower()+"s",[]).append(frag["text"])
        if params.get("classification_options"):
            names={"guid":"GUID_CANDIDATE","string":"STRING","structure":"STRUCTURE_CANDIDATE","pointer table":"POINTER_TABLE_CANDIDATE","unknown":"UNKNOWN"}
            params["classification_candidates"]=[names.get(x.casefold(),x) for x in params["classification_options"]]
        supported=bool(operations and not set(caps)&set(missing_capabilities) and normalized not in unsupported)
        scoped_ops=[]
        for op in operations:
            scoped=[x for x in operation_entries if x.get("operation")==op] or [{"parameters":params}]
            for item in scoped:
                scoped_ops.append({"operation":op,"parameters":item.get("parameters",{}),"artifact_scope":item.get("parameters",{}).get("artifact_scope"),"required_capabilities":OPERATION_REGISTRY.get(op,{}).get("capabilities",[]),"support_status":"SUPPORTED" if op in OPERATION_REGISTRY and not (set(OPERATION_REGISTRY[op].get("capabilities",[]))&set(missing_capabilities)) else "UNSUPPORTED"})
        roles=list(dict.fromkeys(x["role"] for x in fragments))
        diagnostics.append({"source_text":str(raw),"original_method_block":str(raw),"normalized_semantic_block":normalized,"semantic_role":roles,"fragments":fragments,"operation":scoped_ops,"compiled_operations":list(dict.fromkeys(operations)),"parameters":params,"artifact_scope":next((x.get("artifact_scope") for x in scoped_ops if x.get("artifact_scope")),None),"required_capabilities":caps,"support_result":"SUPPORTED" if supported else ("UNSUPPORTED" if normalized in unsupported or set(caps)&set(missing_capabilities) else "NO_OPERATION"),"supported":supported})
    return diagnostics

def find_readonly_artifact(project_root,task):
    root=Path(project_root).resolve();hints=[]
    for value in task.get("input_artifacts",[]):
        if isinstance(value,dict):value=value.get("path") or value.get("name") or value.get("artifact_id") or ""
        name=Path(str(value)).name
        if name and name.lower() not in ("project_root","none","невизначено"):hints.append(name)
    prompt=Path(root/"research"/"tasks"/str(task.get("task_id"))/"ORIGINAL_TASK.txt")
    if prompt.is_file():
        text=prompt.read_text(encoding="utf-8",errors="replace")
        if "navimain.exe" in text.casefold():hints.insert(0,"NAVIMAIN.EXE")
    roots=[root/"research"/"runs",root/"research"/"artifacts",root/"artifacts"]
    wanted={x.casefold() for x in hints}
    db=root/"research"/"db_lab"/"analysis.sqlite"
    if wanted and db.is_file():
        try:
            import sqlite3
            conn=sqlite3.connect(f"file:{db}?mode=ro",uri=True)
            for row in conn.execute("SELECT source_path FROM artifacts ORDER BY source_path"):
                candidate=Path(row[0]).expanduser()
                if candidate.is_file() and candidate.name.casefold() in wanted:return candidate.resolve()
                if candidate.is_dir():
                    for child in candidate.rglob("*"):
                        if child.is_file() and child.name.casefold() in wanted:return child.resolve()
            conn.close()
        except Exception:pass
    for base in roots:
        if not base.is_dir():continue
        for path in base.rglob("*"):
            if not path.is_file() or path.name.casefold() not in wanted:continue
            resolved=path.resolve()
            if root not in resolved.parents:continue
            if "db_lab" in resolved.parts or ".git" in resolved.parts:continue
            return resolved
    return None

def _write_csv(path,rows,fields=None):
    path.parent.mkdir(parents=True,exist_ok=True)
    rows=list(rows)
    if fields is None:fields=list(dict.fromkeys(k for row in rows for k in row.keys()))
    with path.open("w",newline="",encoding="utf-8") as stream:
        writer=csv.DictWriter(stream,fieldnames=fields,extrasaction="ignore");writer.writeheader()
        for row in rows:writer.writerow({k:_csv_value(v) for k,v in row.items()})
def _csv_value(value):return json.dumps(value,ensure_ascii=False) if isinstance(value,(dict,list,tuple)) else value

def _requested_rvas(task):
    text="\n".join(str(x) for x in task.get("methods",[])+task.get("expected_outputs",[]))
    return [int(x,16) for x in re.findall(r"\b0x([0-9a-fA-F]{1,8})\b",text)]

def _requested_call_rva(task,analysis):
    text="\n".join(map(str,task.get("methods",[])))
    m=re.search(r"call[^\n]{0,50}?(0x[0-9a-fA-F]+)",text,re.I) or re.search(r"at\s+(?:RVA\s*)?(0x[0-9a-fA-F]+)",text,re.I)
    if m:return int(m.group(1),16)
    symbol=_requested_symbol(task)
    if symbol:
        imp=next((x for x in analysis.get("imports",[]) if x.get("name")==symbol),None)
        if imp:
            ref=next((x for x in analysis.get("normalized_xrefs",[]) if x.get("target_iat_rva")==imp.get("iat_rva")),None)
            if ref:return int(ref["instruction_rva"])
    return None

def _requested_symbol(task):
    text="\n".join(map(str,task.get("methods",[])+task.get("known_facts",[])))
    m=re.search(r"\?[A-Za-z_?$][A-Za-z0-9_?$@]+",text)
    return m.group(0).rstrip(".,;:") if m else None

def _inspect_region(read,analysis,before,after):
    raw=read["raw_bytes"]; start=read["rva"]; end=start+len(raw)
    strings=[]
    for encoding,width in (("ASCII",1),("UTF16LE",2)):
        i=0
        while i<len(raw):
            p=i
            chars=[]
            while p+(1 if width==1 else 2)<=len(raw):
                if width==1:
                    v=raw[p]; ok=32<=v<127
                else:
                    v=int.from_bytes(raw[p:p+2],"little");ok=32<=v<127
                if not ok:break
                chars.append(chr(v));p+=width
            if len(chars)>=4:strings.append({"rva":start+i,"encoding":encoding,"text":"".join(chars)})
            i=max(p+width,i+width)
    pe=analysis.get("pe",{})
    pointers=[]
    for i in range(0,max(0,len(raw)-3),4):
        value=int.from_bytes(raw[i:i+4],"little"); target=value-int(pe.get("image_base",0)) if value>=int(pe.get("image_base",0)) else value
        if any(int(s["virtual_address"])<=target<int(s["virtual_address"])+max(int(s["virtual_size"]),int(s["raw_size"])) for s in pe.get("sections",[])):
            pointers.append({"source_rva":start+i,"value_va":value,"target_rva":target})
    xrefs=[x for x in analysis.get("normalized_xrefs",[]) if x.get("target_rva") is not None and start<=x["target_rva"]<end]
    alignment=next((n for n in (16,8,4,2) if start%n==0),1)
    classification="STRING" if strings else "POINTER_TABLE_CANDIDATE" if pointers else "GUID_CANDIDATE" if len(raw)>=16 and len(raw)%16==0 else "RAW_DATA"
    return {"rva":start,"length":len(raw),"section":read["section"],"alignment":alignment,"raw_hex":raw.hex(),"possible_strings":strings,"possible_pointers":pointers,"possible_guid_values":[{"rva":start+i,"raw_hex":raw[i:i+16].hex()} for i in range(0,max(0,len(raw)-15),4)],"xrefs_to_region":xrefs,"nearby_referenced_addresses":[x.get("target_rva") for x in xrefs],"classification":classification,"before_bytes":before,"after_bytes":after}

def _save_json(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    def clean(x):
        if isinstance(x,bytes):return x.hex()
        if isinstance(x,dict):return {k:clean(v) for k,v in x.items()}
        if isinstance(x,(list,tuple)):return [clean(v) for v in x]
        return x
    path.write_text(json.dumps(clean(value),ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

def _call_graph(analysis,depth_limit=4):
    refs=analysis.get("normalized_xrefs",[]);calls=[x for x in refs if x.get("xref_type")=="CALL" and x.get("target_rva") is not None]
    entry=analysis.get("entry_point_rva");entry_fn=analysis.get("entry_function") or {}
    start=entry_fn.get("start_rva",entry)
    queue=[(start,0)] if start is not None else [];seen={start} if start is not None else set();edges=[]
    while queue:
        fn,depth=queue.pop(0)
        if depth>=depth_limit:continue
        for ref in calls:
            if ref.get("function_rva")!=fn:continue
            target=ref.get("target_rva");target_fn=next((x.get("start_rva") for x in analysis.get("functions",[]) if x.get("start_rva")<=target<x.get("end_rva")),target)
            edges.append({"caller_rva":fn,"callsite_rva":ref.get("instruction_rva"),"target_rva":target,"callee_function_rva":target_fn,"depth":depth+1})
            if target_fn not in seen:seen.add(target_fn);queue.append((target_fn,depth+1))
    return edges,seen

def _rank(analysis,reachable):
    grouped={}
    for x in analysis.get("normalized_xrefs",[]):
        fn=x.get("function_rva")
        if fn is None or fn not in reachable:continue
        item=grouped.setdefault(fn,{"function_rva":fn,"ordinal_imports":0,"string_xrefs":0,"data_xrefs":0,"direct_calls":0,"score":0,"confidence":"LOW"})
        kind=x.get("xref_type")
        if kind=="IMPORT":item["ordinal_imports"]+=1
        elif kind=="STRING":item["string_xrefs"]+=1
        elif kind=="DATA":item["data_xrefs"]+=1
        elif kind=="CALL":item["direct_calls"]+=1
    for item in grouped.values():
        item["score"]=item["ordinal_imports"]*4+item["string_xrefs"]*3+item["data_xrefs"]+item["direct_calls"]*2
        item["reason"]="Static xref counts only; candidate ranking is a hypothesis, not a semantic label."
        item["recommended_next_inspection"]=f"Inspect function RVA 0x{item['function_rva']:08X}"
    return sorted(grouped.values(),key=lambda x:(-x["score"],x["function_rva"]))[:20]

def _run_operation(operation,ctx):
    entry=operation if isinstance(operation,dict) else {"operation":operation,"parameters":{},"source_method_item":None}
    operation=entry.get("operation"); op_params=entry.get("parameters") or {}; ctx["current_operation"]=entry
    if operation in OPERATION_ALIASES:
        _run_corpus_operation(OPERATION_ALIASES[operation],ctx,op_params);return
    if OPERATION_REGISTRY.get(operation,{}).get("executor_operation")=="SH4_XREF":
        _run_operation({**entry,"operation":"SH4_XREF"},ctx);return
    if operation in CORPUS_EXECUTED_OPERATIONS:
        _run_corpus_operation(operation,ctx,op_params);return
    if operation in {"MULTI_ARTIFACT_SCOPE","CONDITIONAL_FOCUSED_ANALYSIS"}:return
    if operation=="LOAD_ARTIFACT":
        path=find_readonly_artifact(ctx["root"],ctx["task"])
        if not path:raise RuntimeError("INPUT_MISSING: no matching in-project artifact found")
        ctx["artifact_path"]=path;data=path.read_bytes();ctx["artifact_bytes"]=data
        ctx["input_record"]={"source_path":str(path),"size":len(data),"sha256":hashlib.sha256(data).hexdigest()}
        record={"artifact_id":ctx["input_record"]["sha256"][:24],"source_path":str(path),"source_type":"pe_executable","size":ctx["input_record"]["size"],"sha256":ctx["input_record"]["sha256"]}
        ctx["meta"]["input_artifacts"]=[record];ctx["meta"]["input_hashes"]={record["artifact_id"]:record["sha256"]}
        from .tasks import atomic_json
        atomic_json(ctx["run"]/"run.json",ctx["meta"])
    elif operation=="PE_ANALYZE":
        from .artifact_lab.binary_analysis import pe_analyze
        result=pe_analyze(ctx["artifact_bytes"])
        if not result:raise RuntimeError("PE_ANALYZE_FAILED: input is not a supported PE")
        ctx["pe"]=result
    elif operation in ("SH4_ABI_ANALYSIS","MSVC_DECORATED_SYMBOL_PARSE","READ_RVA_BYTES","HEX_VIEW","ASCII_VIEW","UTF16LE_VIEW","WINDOWS_GUID_INTERPRET","INSPECT_DATA_REGION","SH4_CALL_ARGUMENT_TRACE","SH4_RETURN_VALUE_TRACE","SH4_OUT_PARAMETER_TRACE","SH4_OBJECT_FLOW_TRACE","VTABLE_CALL_DETECTION","OBJECT_FLOW_REPORT"):
        from . import semantic_analysis as sem
        task=ctx["task"]; a=ctx.get("analysis",{}); text="\n".join(map(str,task.get("methods",[])))
        rvas=[int(op_params["rva"])] if "rva" in op_params else _requested_rvas(task); call_rva=int(op_params["call_rva"]) if "call_rva" in op_params else _requested_call_rva(task,a)
        symbol=op_params.get("decorated_symbol") or _requested_symbol(task)
        if operation=="SH4_ABI_ANALYSIS":ctx["abi_analysis"]=sem.sh4_wince_abi()
        elif operation=="MSVC_DECORATED_SYMBOL_PARSE":ctx["decorated_symbol_analysis"]=sem.parse_msvc_decorated_symbol(symbol or text)
        elif operation=="READ_RVA_BYTES":
            if not ctx.get("pe"):
                from .artifact_lab.binary_analysis import pe_analyze
                ctx["pe"]=pe_analyze(ctx["artifact_bytes"])
            if not rvas:raise RuntimeError("RVA_DATA_READ_FAILED: no RVA specified")
            length=int(op_params.get("length",64))
            try:ctx["rva_data"]=sem.read_rva_bytes(ctx["artifact_bytes"],ctx["pe"],rvas[0],length)
            except ValueError as exc:raise RuntimeError("RVA_DATA_READ_FAILED: "+str(exc)) from exc
            ctx["rva_reads"].append(ctx["rva_data"])
            _save_json(ctx["run"]/"data"/f"rva_bytes_{ctx['rva_data']['rva']:08X}.json",ctx["rva_data"])
            _save_json(ctx["run"]/"data"/"rva_bytes.json",ctx["rva_data"])
        elif operation=="HEX_VIEW":
            if "rva_data" not in ctx:raise RuntimeError("HEX_VIEW_REQUIRES_READ_RVA_BYTES")
            ctx["hex_view"]=sem.hex_view(ctx["rva_data"]["raw_bytes"])
        elif operation=="ASCII_VIEW":
            if "rva_data" not in ctx:raise RuntimeError("ASCII_VIEW_REQUIRES_READ_RVA_BYTES")
            ctx["ascii_view"]=sem.ascii_view(ctx["rva_data"]["raw_bytes"])
        elif operation=="UTF16LE_VIEW":
            if "rva_data" not in ctx:raise RuntimeError("UTF16LE_VIEW_REQUIRES_READ_RVA_BYTES")
            ctx["utf16le_view"]=sem.utf16le_view(ctx["rva_data"]["raw_bytes"])
        elif operation=="WINDOWS_GUID_INTERPRET":
            if "rva_data" not in ctx:
                if not ctx.get("pe"):
                    from .artifact_lab.binary_analysis import pe_analyze
                    ctx["pe"]=pe_analyze(ctx["artifact_bytes"])
                if not rvas:raise RuntimeError("GUID_INTERPRETATION_REQUIRES_RVA")
                ctx["rva_data"]=sem.read_rva_bytes(ctx["artifact_bytes"],ctx["pe"],rvas[0],16)
            evidence=[]; source=ctx["rva_data"]
            if a and any(x.get("target_rva")==ctx["rva_data"]["rva"] for x in a.get("normalized_xrefs",[])):evidence.append("static xref targets this RVA")
            trace=ctx.get("call_argument_trace",{})
            if any(str(arg.get("value","")).lower() in (f"0x{ctx['rva_data']['va']:x}",f"0x{ctx['rva_data']['rva']:x}") for arg in trace.get("arguments",[])):evidence.append("address is passed as a call argument")
            if evidence and "address is passed as a call argument" in evidence:evidence.append("address passed at this exact byte source")
            guid=sem.windows_guid_interpret(source["raw_bytes"][:16],evidence)
            guid.update({"source_rva":source["rva"],"source_va":source["va"],"source_file_offset":source["file_offset"],"source_section":source["section"],"source_operation_id":entry.get("operation_id") or f"{operation}:{entry.get('source_method_item')}:{source['rva']:X}"})
            ctx["guid_interpretation"]=guid
        elif operation=="INSPECT_DATA_REGION":
            if not ctx.get("pe"):
                from .artifact_lab.binary_analysis import pe_analyze
                ctx["pe"]=pe_analyze(ctx["artifact_bytes"])
            if not rvas:raise RuntimeError("INSPECT_DATA_REGION_REQUIRES_RVA")
            bm=re.search(r"before\s+(\d+).{0,20}after\s+(\d+)",text,re.I); before,after=(int(op_params.get("before_bytes",bm.group(1) if bm else 32)),int(op_params.get("after_bytes",bm.group(2) if bm else 32)))
            base=int(op_params.get("rva",rvas[0]))
            base=rvas[0]; section=next((s for s in ctx["pe"]["sections"] if int(s["virtual_address"])<=base<int(s["virtual_address"])+int(s["raw_size"])),None)
            if section is None:raise RuntimeError("INSPECT_DATA_REGION_RVA_NOT_IN_RAW_SECTION")
            start=max(int(section["virtual_address"]),base-before); end=min(int(section["virtual_address"])+int(section["raw_size"]),base+after)
            read=sem.read_rva_bytes(ctx["artifact_bytes"],ctx["pe"],start,end-start)
            ctx["data_region"]= _inspect_region(read,{"pe":ctx["pe"],**a},before,after);ctx["data_region"]["center_rva"]=base;ctx["data_regions"].append(ctx["data_region"])
        elif operation=="SH4_CALL_ARGUMENT_TRACE":
            if call_rva is None:raise RuntimeError("SH4_CALL_ARGUMENT_TRACE_REQUIRES_CALL_RVA")
            ctx["call_argument_trace"]=sem.trace_registers_at_call(a,call_rva,symbol)
        elif operation=="SH4_RETURN_VALUE_TRACE":
            if call_rva is None:raise RuntimeError("SH4_RETURN_VALUE_TRACE_REQUIRES_CALL_RVA")
            ctx["return_value_trace"]=sem.trace_local_value_flow(a,call_rva+4,0,"return")
        elif operation=="SH4_OUT_PARAMETER_TRACE":
            if call_rva is None:raise RuntimeError("SH4_OUT_PARAMETER_TRACE_REQUIRES_CALL_RVA")
            location=op_params.get("argument_location") or re.search(r"(?:argument|arg)\s*(?:location\s*)?(R[4-7]|stack\s*\+\s*0x[0-9a-f]+)",text,re.I)
            ctx["out_parameter_trace"]=sem.trace_out_parameter(a,call_rva,location if isinstance(location,str) else location.group(1) if location else None,symbol)
        elif operation=="SH4_OBJECT_FLOW_TRACE":
            start=call_rva if call_rva is not None else (rvas[0] if rvas else a.get("entry_point_rva",0))
            start=int(start)+4 if call_rva is not None else int(start)
            rmatch=re.search(r"(?:register|pointer|value)\s*R(\d+)",text,re.I);reg=int(rmatch.group(1)) if rmatch else 0
            endmatch=re.search(r"until at least\s+(?:RVA\s*)?(0x[0-9a-f]+|\d+)",text,re.I)
            end_rva=int(endmatch.group(1),0) if endmatch else None
            out_seed="@R14+0x8" if re.search(r"out (?:parameter|storage)|local backing storage",text,re.I) and ctx.get("out_parameter_trace",{}).get("argument_location","").upper()=="STACK+0X14" else None
            ctx["object_flow_trace"]=sem.trace_object_flow(a,start,reg,end_rva=end_rva,start_location=out_seed)
        elif operation=="VTABLE_CALL_DETECTION":ctx["vtable_call_analysis"]=sem.detect_vtable_calls(a)
        elif operation=="OBJECT_FLOW_REPORT":
            steps=ctx.get("object_flow_trace",{}).get("steps",[])
            ctx["object_flow_report"]="\n".join(f"0x{x['instruction_rva']:08X} {x['operation']}: {x['source_location']} -> {x['destination_location']}" for x in steps) or "NO EVIDENCE RECOVERED: no bounded object-flow links were established."
        for key in ("abi_analysis","decorated_symbol_analysis","call_argument_trace","return_value_trace","out_parameter_trace","object_flow_trace","vtable_call_analysis","guid_interpretation","data_region","hex_view","ascii_view","utf16le_view"):
            if key in ctx:_save_json(ctx["run"]/"data"/(key+".json"),ctx[key])
        if "object_flow_report" in ctx:(ctx["run"]/"data"/"object_flow_report.txt").write_text(ctx["object_flow_report"]+"\n",encoding="utf-8")
    elif operation=="SH4_DISASSEMBLE":
        from .sh4_analysis import disassemble_module
        if op_params.get("condition"):
            wanted=set(op_params["condition"].get("any_hit_pattern_ids",[]));analyses=[]
            for hit in ctx.get("corpus_pattern_hits",[]):
                if hit.get("pattern_id") not in wanted or not hit.get("is_pe"):continue
                path=hit["source_path"]
                if any(x.get("source_path")==path for x in analyses):continue
                result=disassemble_module(path)
                analyses.append({"source_path":path,"pattern_id":hit["pattern_id"],"hit_rva":(hit.get("pe_mapping") or {}).get("rva"),"analysis":result})
            ctx["conditional_analyses"]=analyses;return
        if "analysis" not in ctx:
            entry=ctx["task"].get("parameters",{}).get("entry_rva")
            result=disassemble_module(ctx["artifact_path"],entry_rva=int(str(entry),0) if entry else None)
            if result.get("status")!="SUPPORTED":raise RuntimeError("SH4_DISASSEMBLY_FAILED: "+str(result.get("status")))
            ctx["analysis"]=result
        if "start_rva" in op_params and "end_rva" in op_params:
            lo,hi=int(op_params["start_rva"]),int(op_params["end_rva"])
            rows=[x for x in ctx["analysis"].get("instructions",[]) if lo<=int(x["rva"])<=hi]
            ctx.setdefault("disassembly_ranges",[]).append({"start_rva":lo,"end_rva":hi,"instruction_count":len(rows)})
            (ctx["run"] /"data"/f"disassembly_{lo:08X}_{hi:08X}.txt").write_text("\n".join(f"0x{x['rva']:08X}  {x.get('bytes','')}  {x.get('operands','')}" for x in rows)+"\n",encoding="utf-8")
    elif operation in ("BUILD_CALL_GRAPH","SH4_XREF","IMPORT_XREF","STRING_XREF","DATA_XREF","SEARCH_STRINGS","SEARCH_EXTENSIONS","RANK_FUNCTIONS"):
        if op_params.get("condition") and "conditional_analyses" in ctx:
            wanted=set(op_params["condition"].get("any_hit_pattern_ids",[]));refs=[]
            for module in ctx["conditional_analyses"]:
                if module.get("pattern_id") not in wanted:continue
                analysis=module["analysis"]
                if analysis.get("status")!="SUPPORTED":continue
                hit_rva=module.get("hit_rva")
                related=[x for x in analysis.get("normalized_xrefs",[]) if hit_rva is not None and x.get("target_rva") is not None and abs(int(x["target_rva"])-int(hit_rva))<16]
                functions={x.get("function_rva") for x in related if x.get("function_rva") is not None}
                related.extend(x for x in analysis.get("normalized_xrefs",[]) if x.get("function_rva") in functions and x not in related)
                refs.extend({**x,"source_path":module["source_path"],"matched_pattern_id":module["pattern_id"]} for x in related)
            if operation=="SH4_XREF":ctx["xrefs"]=refs
            elif operation=="IMPORT_XREF":ctx["ordinal_callers"]=[x for x in refs if x.get("xref_type")=="IMPORT"]
            elif operation=="STRING_XREF":ctx["string_xrefs"]=[x for x in refs if x.get("xref_type")=="STRING"]
            return
        if "analysis" not in ctx:raise RuntimeError("OPERATION_PREREQUISITE_MISSING: SH4_DISASSEMBLE")
        a=ctx["analysis"]
        if operation=="BUILD_CALL_GRAPH":ctx["callgraph"],ctx["reachable"]=_call_graph(a,4)
        elif operation=="SH4_XREF":ctx["xrefs"]=a.get("normalized_xrefs",[])
        elif operation=="IMPORT_XREF":ctx["ordinal_callers"]=[x for x in a.get("normalized_xrefs",[]) if x.get("xref_type")=="IMPORT" and x.get("ordinal") is not None]
        elif operation=="STRING_XREF":ctx["string_xrefs"]=[x for x in a.get("normalized_xrefs",[]) if x.get("xref_type")=="STRING"]
        elif operation=="DATA_XREF":ctx["data_xrefs"]=[x for x in a.get("normalized_xrefs",[]) if x.get("xref_type")=="DATA"]
        elif operation=="SEARCH_STRINGS":ctx["strings"]=a.get("strings",[])
        elif operation=="SEARCH_EXTENSIONS":
            wanted=re.findall(r"\.[A-Z0-9]{2,5}\b|ZONE\.CFG",Path(ctx["task_path"]).read_text(encoding="utf-8").upper())
            ctx["extension_matches"]=[s for s in a.get("strings",[]) if any(term in str(s.get("value","")).upper() for term in wanted)]
        elif operation=="RANK_FUNCTIONS":
            if "BUILD_CALL_GRAPH" in [x.get("operation") if isinstance(x,dict) else x for x in ctx["task"].get("execution_plan",[])]:
                reachable=ctx.get("reachable",set())
            else:
                reachable={x.get("function_rva") for x in a.get("normalized_xrefs",[]) if x.get("function_rva") is not None}
            ctx["ranked_functions"]=_rank(a,reachable)
    elif operation=="EXPORT_CSV":
        data=ctx["run"]/"data"
        _write_csv(data/"navimain_callgraph.csv",ctx.get("callgraph",[]))
        _write_csv(data/"navimain_functions.csv",[f for f in ctx.get("analysis",{}).get("functions",[]) if f.get("start_rva") in ctx.get("reachable",set())])
        _write_csv(data/"ordinal_callers.csv",ctx.get("ordinal_callers",[]))
        _write_csv(data/"string_xrefs.csv",ctx.get("string_xrefs",[]))
        _write_csv(data/"ranked_functions.csv",ctx.get("ranked_functions",[]))
        _write_csv(data/"indirect_call_xrefs.csv",ctx.get("analysis",{}).get("indirect_call_xrefs",[]),["module","caller_function_rva","call_instruction_rva","register","literal_rva","raw_target","resolved_target_rva","target_type","import_dll","import_name","import_ordinal","confidence"])
        _write_csv(data/"literal_pool_resolutions.csv",ctx.get("analysis",{}).get("literal_pool_resolutions",[]),["module","instruction_rva","register","literal_rva","raw_value","resolved_va","resolved_rva","resolution_type","confidence"])
        _write_csv(data/"extension_matches.csv",ctx.get("extension_matches",[]))
        top=(ctx.get("ranked_functions") or [None])[0]
        ins=[]
        if top:
            fn=top["function_rva"]
            ins=[x for x in ctx["analysis"].get("instructions",[]) if x.get("function_start")==fn][:256]
        (data/"top_candidate_disassembly.txt").write_text("\n".join(f"0x{x['rva']:08X}  {x['bytes']}  {x['operands']}" for x in ins)+"\n",encoding="utf-8")
    elif operation=="GENERATE_REPORT":_generate_report(ctx)
    elif operation=="PACKAGE_RESULTS":
        from .tasks import package_run
        result=package_run(ctx["run"])
        if result.get("status")!="READY":raise RuntimeError("CHATGPT_PACKAGE_NOT_READY")
        ctx["package"]=result
    else:raise RuntimeError("UNREGISTERED_OPERATION: "+str(operation))

def _generate_report(ctx):
    if ctx.get("task",{}).get("executor_mode")=="STRICT_PLAN":
        _strict_report(ctx);return
    run=ctx["run"];task=ctx["task"];a=ctx.get("analysis",{});reach=ctx.get("reachable",set());ordinals=ctx.get("ordinal_callers",[]);strings=ctx.get("string_xrefs",[]);ranked=ctx.get("ranked_functions",[])
    unresolved=[x for x in a.get("indirect_call_xrefs",[]) if x.get("target_type")=="UNRESOLVED"]
    graph_failed=bool(a.get("indirect_call_xrefs")) and len(reach)<=1 and bool(unresolved)
    plan=task.get("execution_plan",[])
    names=[x.get("operation") if isinstance(x,dict) else x for x in plan]
    blockers=["INDIRECT_CALL_TARGETS_UNRESOLVED"] if graph_failed else []
    for entry in plan:
        if not isinstance(entry,dict):continue
        op=entry.get("operation");p=entry.get("parameters",{})
        if op=="READ_RVA_BYTES" and p.get("rva") is not None:
            if not any(x.get("rva")==int(p["rva"]) for x in ctx.get("rva_reads",[])):blockers.append(f"REQUESTED_RVA_READ_MISSING:0x{int(p['rva']):X}")
        if op=="INSPECT_DATA_REGION" and p.get("rva") is not None:
            if not any(x.get("center_rva")==int(p["rva"]) for x in ctx.get("data_regions",[])):blockers.append(f"REQUESTED_REGION_MISSING:0x{int(p['rva']):X}")
    trace=ctx.get("call_argument_trace",{})
    if "SH4_CALL_ARGUMENT_TRACE" in names and any("@(" in str(x.get("operands","")) and "R15" in str(x.get("operands","")) for x in trace.get("source_instructions",[])) and not trace.get("stack_arguments"):
        blockers.append("ARGUMENT_TRACE_OMITTED_RECOGNIZED_STACK_STORES")
    if ctx.get("parameter_mismatch"):blockers.append("EXECUTION_PARAMETER_MISMATCH")
    finding_status=ctx.get("finding_status_override") or ("INCONCLUSIVE" if graph_failed or blockers else "COMPLETED")
    if graph_failed: ranked=[]
    answers=[]
    for i,q in enumerate(task.get("report_questions",[]),1):
        question=str(q).casefold(); answer="INCONCLUSIVE: no matching operation result was recovered."
        if any(k in question for k in ("argument","createinstance","passed")) and ctx.get("call_argument_trace"):
            answer="Evidence: "+json.dumps(ctx["call_argument_trace"].get("arguments",[])+ctx["call_argument_trace"].get("stack_arguments",[]),ensure_ascii=False)
        elif any(k in question for k in ("guid","bytes","rva")) and ctx.get("rva_reads"):
            answer="Evidence: "+json.dumps([{k:v for k,v in x.items() if k!="raw_bytes"} for x in ctx["rva_reads"]],ensure_ascii=False)
        elif any(k in question for k in ("out parameter","out object","object flow","vtable")) and ctx.get("out_parameter_trace"):
            answer="Evidence: "+json.dumps(ctx.get("out_parameter_trace"),ensure_ascii=False)
        elif any(k in question for k in ("string","identity","class","interface")) and strings:
            answer="Evidence: "+json.dumps(strings[:32],ensure_ascii=False)
        elif i==12 and ranked:answer="Evidence-derived pivot candidate: "+json.dumps(ranked[0],ensure_ascii=False)
        answers.append(f"{i}. {q}\n   {answer}")
    lines=[f"# {task.get('title','Research task')}","",f"Executor: GENERIC_RESEARCH_RUNNER","",f"Input: {ctx.get('input_record',{}).get('source_path','not resolved')}",f"SHA256: {ctx.get('input_record',{}).get('sha256','')}",f"Entry RVA: {a.get('entry_point_rva')}",f"Reachable graph nodes (up to 4 call levels): {len(reach)}",f"Call edges: {len(ctx.get('callgraph',[]))}",f"Ordinal caller xrefs: {len(ordinals)}",f"String xrefs: {len(strings)}","","## Report questions",*answers,"","## Constraints","- Analysis is static and read-only on source artifacts.","- Function names and semantic categories are not inferred as facts.","- Missing literal xrefs do not prove that a format is unused."]
    report="\n".join(lines)+"\n";(ctx["run"]/"REPORT.md").write_text(report,encoding="utf-8")
    (ctx["run"]/"REPORT.html").write_text("<!doctype html><meta charset='utf-8'><title>Task report</title><pre>"+html.escape(report)+"</pre>",encoding="utf-8")
    summary={"status":finding_status,"finding_status":finding_status,"blockers":blockers,"executor":"GENERIC_RESEARCH_RUNNER","task_id":task.get("task_id"),"task_revision":task.get("task_revision",1),"input":ctx.get("input_record"),"reachable_nodes":len(reach),"call_edges":len(ctx.get("callgraph",[])),"ordinal_callers":len(ordinals),"string_xrefs":len(strings),"top_candidate_rva":ranked[0].get("function_rva") if ranked else None,"source_artifact_modified":False}
    ctx["summary"]=summary;(ctx["run"]/"CHATGPT_SUMMARY.txt").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

def _strict_get_result(ctx, reference):
    if not reference:return None
    sid,field=reference.split(".",1)
    result=ctx.get("strict_step_results",{}).get(sid,{})
    return result.get(field) if isinstance(result,dict) else None

def _strict_step_result(ctx, operation):
    op=operation.get("operation")
    if op in {"POSITIVE_CONTROL","POSITIVE_CONTROL_VALIDATION"}:return {"hits":(ctx.get("positive_control") or {}).get("hits",[])}
    fields={"CORPUS_BINARY_PATTERN_SEARCH":("hits","corpus_pattern_hits"),"PE_FILE_OFFSET_TO_RVA":("mappings","pe_offset_mappings"),"PE_FILE_OFFSET_MAPPING":("mappings","pe_offset_mappings"),"CORPUS_CODE_XREF_ANALYSIS":("analyses","corpus_code_xrefs"),"CORPUS_STRING_SEARCH":("hits","corpus_string_hits"),"CORPUS_SYMBOL_SEARCH":("hits","corpus_symbol_hits"),"BUILD_RELATIONSHIP_TABLE":("rows","relationship_table"),"RANK_ARTIFACTS":("rows","ranked_artifacts")}
    if op in fields:
        field,key=fields[op];return {field:ctx.get(key,[])}
    if op=="LOAD_ARTIFACT":return {"artifact":ctx.get("input_record",{})}
    if op=="PE_ANALYZE":return {"analysis":ctx.get("pe",{})}
    if op=="READ_RVA_BYTES":return {"bytes":ctx.get("rva_data",{})}
    return {}

def _strict_report(ctx):
    task=ctx["task"];run=ctx["run"];lang=__import__("os").environ.get("NCDR_UI_LANGUAGE","uk")
    title=task.get("title","Research task");lines=[f"# {title}","","Format: NCDR_TASK_PLAN_V1",f"Task ID: {task.get('task_id')}",f"Revision: {task.get('task_revision',1)}","","## Report questions"]
    for q in (task.get("strict_report") or {}).get("questions",[]):
        label=q.get("text",{});label=label.get(lang) or label.get("en") or label.get("uk") or ""
        source=q.get("source",{});sid=source.get("step");flt=source.get("filter") or {};field=flt.get("output","hits")
        rows=ctx.get("strict_step_results",{}).get(sid,{}).get(field,[])
        if flt.get("pattern") is not None:rows=[x for x in rows if isinstance(x,dict) and x.get("pattern_id")==flt["pattern"]]
        answer="EVIDENCE: "+json.dumps(rows[:50],ensure_ascii=False,sort_keys=True) if rows else "INCONCLUSIVE: the specified evidence source contains no matching evidence."
        lines.extend(["",f"### {label}","",answer])
    control=ctx.get("positive_control")
    if control is not None:lines.extend(["","","## Positive controls","",f"Status: {'PASS' if control.get('valid') else 'FAIL'}; found: {', '.join(control.get('found_pattern_ids',[]))}"])
    lines.extend(["","","## Step execution",""])
    for row in ctx.get("strict_step_log",[]):lines.append(f"- {row['step_id']}: {row['operation']} · {row['status']} · {row.get('result_count',0)} results")
    report="\n".join(lines)+"\n";(run/"REPORT.md").write_text(report,encoding="utf-8")
    (run/"REPORT.html").write_text("<!doctype html><meta charset='utf-8'><title>Research report</title><pre>"+html.escape(report)+"</pre>",encoding="utf-8")
    hits=ctx.get("corpus_pattern_hits",[]);research="INVALID" if control is not None and not control.get("valid") else ("STRONG_EVIDENCE" if hits else "INCONCLUSIVE")
    ctx["summary"]={"status":research,"finding_status":research,"research_status":research,"technical_status":"RUNNING","plan_format":"NCDR_TASK_PLAN_V1","task_id":task.get("task_id"),"task_revision":task.get("task_revision",1),"plan_sha256":task.get("plan_sha256"),"pattern_hit_count":len(hits),"positive_control":control,"source_artifact_modified":False}

def _strict_write_outputs(ctx):
    for out in ctx["task"].get("strict_outputs",[]):
        name=out["filename"];kind=out["type"]
        if kind=="csv":
            rows=_strict_get_result(ctx,out["source"])
            if not isinstance(rows,list):raise RuntimeError("STRICT_OUTPUT_SOURCE_NOT_A_LIST")
            cols=sorted({k for row in rows if isinstance(row,dict) for k in row})
            with (ctx["run"]/name).open("w",encoding="utf-8",newline="") as f:
                writer=csv.DictWriter(f,fieldnames=cols or ["status"],extrasaction="ignore");writer.writeheader();writer.writerows(rows)
        elif kind=="report_md" and name!="REPORT.md" and (ctx["run"]/"REPORT.md").exists():
            (ctx["run"]/"REPORT.md").replace(ctx["run"]/name)

def validate_strict_task(task_path,project_root,language="uk"):
    """Production runner dry-run: validate strict source, hash, scope and routes without executing research."""
    task_path=Path(task_path);root=Path(project_root);task=json.loads(task_path.read_text(encoding="utf-8"))
    if task.get("executor_mode")!="STRICT_PLAN":return {"status":"FAIL","issues":["TASK_NOT_STRICT_PLAN"]}
    from .strict_plan import validate_plan,PlanError,to_task
    plan_file=task_path.parent/"TASK_PLAN.yaml"
    if not plan_file.is_file():return {"status":"FAIL","issues":["STRICT_PLAN_MISSING"]}
    raw=plan_file.read_text(encoding="utf-8");digest=hashlib.sha256(raw.encode("utf-8")).hexdigest()
    if digest!=task.get("plan_sha256"):return {"status":"FAIL","issues":["STRICT_PLAN_SHA_MISMATCH"]}
    try:preview=validate_plan(raw,root,language)
    except PlanError as exc:return {"status":"FAIL","issues":exc.issues}
    if not preview.get("run_enabled"):return {"status":"FAIL","issues":["EMPTY_ARTIFACT_SCOPE: Не знайдено артефактів для заданої області пошуку."]}
    fresh=to_task(preview,raw);plan=fresh["execution_plan"];issues=[]
    from .tasks import CAPABILITY_REGISTRY,AVAILABLE_CAPABILITIES
    for operation in plan:
        op=operation["operation"];entry=OPERATION_REGISTRY.get(op)
        if not entry or not entry.get("implementation"):issues.append("Unknown operation: "+str(op));continue
        for cap in entry.get("capabilities",[]):
            if cap not in AVAILABLE_CAPABILITIES or CAPABILITY_REGISTRY.get(cap,{}).get("status")=="UNSUPPORTED":issues.append("Missing required capability: "+cap)
    for step in preview["steps"]:
        scope=step["params"].get("artifact_scope",preview["scope"]);rows,missing=_catalog_artifacts(root,scope,step["params"].get("file_type_filters"))
        if scope and not rows:issues.append("EMPTY_ARTIFACT_SCOPE: Не знайдено артефактів для заданої області пошуку.")
    controls=preview.get("controls_validation",[])
    return {"status":"PASS" if not issues else "FAIL","plan_format":"NCDR_TASK_PLAN_V1","task_id":preview["task_id"],"task_revision":task.get("task_revision",1),"plan_schema_version":preview["plan_schema_version"],"plan_sha256":digest,"artifact_count":preview["scope_artifact_count"],"step_count":len(preview["steps"]),"operation_count":len(plan),"controls":controls,"issues":issues}

def run_generic_research_task(task_path,project_root):
    from .tasks import create_run,finish_run,register_run,atomic_json
    task_path=Path(task_path);root=Path(project_root);task=json.loads(task_path.read_text(encoding="utf-8"));plan=task.get("execution_plan",[])
    if task.get("executor_mode")=="STRICT_PLAN":
        dry=validate_strict_task(task_path,root)
        if dry["status"]!="PASS":raise RuntimeError("STRICT_PLAN_VALIDATION_FAILED: "+"; ".join(dry.get("issues",[])))
        raw=(task_path.parent/"TASK_PLAN.yaml").read_text(encoding="utf-8")
        from .strict_plan import validate_plan,to_task
        preview=validate_plan(raw,root)
        fresh=to_task(preview,raw);task.update({k:fresh[k] for k in ("execution_plan","strict_steps","strict_controls","strict_outputs","strict_report","strict_scope")})
        task["patterns"]=preview["patterns"];plan=task["execution_plan"]
    plan_names=[x.get("operation") if isinstance(x,dict) else x for x in plan]
    unknown=[op for op in plan_names if op not in OPERATION_REGISTRY]
    if unknown:raise RuntimeError("UNREGISTERED_OPERATION: "+", ".join(unknown))
    missing=[]
    from .tasks import CAPABILITY_REGISTRY,AVAILABLE_CAPABILITIES
    for op in plan_names:
        for cap in OPERATION_REGISTRY[op]["capabilities"]:
            if cap not in AVAILABLE_CAPABILITIES or CAPABILITY_REGISTRY.get(cap,{}).get("status")=="UNSUPPORTED":missing.append(cap)
    if missing:raise RuntimeError("MISSING_MANDATORY_CAPABILITY: "+", ".join(sorted(set(missing))))
    run,meta,_=create_run(root,task_path,task,[]);meta.update({"executor":"GENERIC_RESEARCH_RUNNER","execution_plan":plan});meta["status"]="RUNNING";atomic_json(run/"run.json",meta);register_run(root,run,meta)
    ctx={"root":root,"task":task,"task_path":task_path,"run":run,"meta":meta,"summary":{},"started":__import__("time").time(),"rva_reads":[],"data_regions":[]}
    try:
        total=len(plan)
        from .tasks import emit_progress
        from datetime import datetime,timezone
        ctx["strict_step_results"]={};ctx["strict_step_log"]=[]
        for index,operation in enumerate(plan,1):
            op_name=operation.get("operation") if isinstance(operation,dict) else operation
            op_parameters=operation.get("parameters",{}) if isinstance(operation,dict) else {}
            step_id=operation.get("strict_step_id") if isinstance(operation,dict) else None
            row={"step_id":step_id or op_name,"operation":op_name,"resolved_parameters":operation.get("strict_original_params",op_parameters) if isinstance(operation,dict) else op_parameters,"resolved_artifact_count":None,"start":datetime.now(timezone.utc).isoformat(),"finish":None,"status":"RUNNING","result_count":0,"error":None}
            if ctx.get("halt_analysis") and op_name not in {"GENERATE_REPORT","PACKAGE_RESULTS"}:
                row["status"]="SKIPPED_CONTROL_FAILED";row["finish"]=datetime.now(timezone.utc).isoformat();ctx["strict_step_log"].append(row);continue
            try:
                if step_id:
                    ref=operation.get("strict_input");input_rows=_strict_get_result(ctx,ref)
                    if ref and input_rows is None:raise RuntimeError("UNKNOWN_STEP_OUTPUT: "+str(ref))
                    if ref and isinstance(input_rows,list) and operation.get("strict_where"):
                        from .strict_plan import condition_matches
                        input_rows=[x for x in input_rows if condition_matches(x,operation["strict_where"])]
                    if ref:op_parameters["_input_rows"]=input_rows
                    gate=operation.get("strict_condition")
                    if gate:
                        from .strict_plan import condition_matches
                        candidates=input_rows if isinstance(input_rows,list) else [input_rows or {}]
                        if not any(condition_matches(x,gate) for x in candidates):
                            row["status"]="SKIPPED_CONDITION";row["finish"]=datetime.now(timezone.utc).isoformat();ctx["strict_step_log"].append(row);ctx["strict_step_results"][step_id]={};continue
                scope=op_parameters.get("artifact_scope")
                if scope:row["resolved_artifact_count"]=len(_catalog_artifacts(root,scope,op_parameters.get("file_type_filters"))[0])
                emit_progress(op_name,op_name,index,total,index-1,total,"operations",ctx["started"])
                _run_operation(operation,ctx)
                if step_id:
                    ctx["strict_step_results"][step_id]=_strict_step_result(ctx,operation)
                    row["result_count"]=sum(len(v) for v in ctx["strict_step_results"][step_id].values() if isinstance(v,list))
                row["status"]="COMPLETED"
            except Exception as exc:
                row["status"]="FAILED";row["error"]=str(exc);raise
            finally:
                row["finish"]=datetime.now(timezone.utc).isoformat();ctx["strict_step_log"].append(row)
        if task.get("executor_mode")=="STRICT_PLAN":
            _strict_write_outputs(ctx)
            atomic_json(run/"execution-log.json",ctx.get("strict_step_log",[]))
        if not (run/"REPORT.md").exists():_generate_report(ctx)
        summary=ctx.get("summary") or {"status":"INCONCLUSIVE","executor":"GENERIC_RESEARCH_RUNNER","task_id":task.get("task_id"),"source_artifact_modified":False}
        if task.get("executor_mode")=="STRICT_PLAN":summary["technical_status"]="COMPLETED"
        finish_run(run,meta,"COMPLETED",summary)
        from .tasks import package_run
        packaged=package_run(run)
        if "PACKAGE_RESULTS" in plan_names and packaged.get("status")!="READY":raise RuntimeError("CHATGPT_PACKAGE_NOT_READY")
        summary["package"]={"status":packaged.get("status"),"path":str(run/"CHATGPT_PACKAGE.zip") if packaged.get("status")=="READY" else ""}
        (run/"CHATGPT_SUMMARY.txt").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        finish_run(run,meta,"COMPLETED",summary);packaged=package_run(run)
        if packaged.get("status")=="READY":summary["package"]={"status":"READY","path":str(run/"CHATGPT_PACKAGE.zip")}
        finish_run(run,meta,"COMPLETED",summary);register_run(root,run,meta)
        return {"status":"COMPLETED","run_path":str(run),"report_path":str(run/"REPORT.md"),"package_path":str(run/"CHATGPT_PACKAGE.zip") if packaged.get("status")=="READY" else "","summary":summary}
    except Exception as exc:
        finish_run(run,meta,"FAILED",ctx.get("summary",{}),errors=[str(exc)])
        try:register_run(root,run,meta)
        except Exception:pass
        raise
