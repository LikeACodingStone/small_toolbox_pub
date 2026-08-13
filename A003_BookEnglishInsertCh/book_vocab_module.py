#!/usr/bin/env python3
import configparser
import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_FILE = SCRIPT_DIR / "config.ini"
FILTER_FILE = SCRIPT_DIR / "filter.txt"
OLLAMA_API = "http://localhost:11434/api/generate"
WORD_RE = re.compile(r"\b[A-Za-z][A-Za-z'-]*\b")

logger = logging.getLogger(__name__)

SKIP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "can", "did", "do", "for",
    "from", "get", "go", "had", "has", "have", "he", "her", "him", "his", "how", "i",
    "if", "in", "is", "it", "its", "me", "my", "no", "not", "of", "on", "or", "our",
    "out", "she", "so", "the", "to", "too", "up", "us", "was", "we", "who", "why", "you",
    "aren", "couldn", "didn", "doesn", "don", "hadn", "hasn", "haven", "isn", "ll", "re",
    "shan", "shouldn", "ve", "wasn", "weren", "won", "wouldn",
    "ai", "api", "azw", "azw3", "cpu", "cuda", "epub", "gpu", "html", "http", "https",
    "ipa", "json", "llm", "mobi", "ocr", "pdf", "png", "txt", "xml",
}

DEFAULT_DIFFICULTY_CONFIG = {
    "advanced_levels": {"C1", "C2"},
    "min_candidate_length": 5,
    "b1_min_length": 8,
    "b1_frequency_threshold": 0.000003,
    "b2_min_length": 8,
    "b2_frequency_threshold": 0.000012,
    "unknown_min_length": 8,
    "unknown_frequency_threshold": 0.000003,
}

DEFAULT_TRANSLATION_CONFIG = {
    "segments_per_translation": 1,
    "use_context_meaning": True,
    "max_meaning_chars": 8,
    "retry_on_verbose_meaning": True,
    "ambiguous_meaning_policy": "skip",
    "ollama_temperature": 0.0,
    "ollama_model": "qwen2.5:7b",
    "repeat_window_words": 250,
    "translation_batch_size": 8,
    "max_context_chars": 1800,
    "ollama_timeout_seconds": 240,
    "ollama_request_retries": 2,
    "ollama_retry_sleep_seconds": 3,
    "ipa_provider": "auto",
}

DEFAULT_PROPER_NOUN_CONFIG = {
    "enabled": True,
    "model": "en_core_web_sm",
    "entity_labels": {"PERSON", "GPE", "LOC", "FAC", "ORG"},
    "skip_words": set(),
}

_DIFFICULTY_CONFIG_CACHE = {"mtime": None, "config": None}
_TRANSLATION_CONFIG_CACHE = {"mtime": None, "config": None}
_PROPER_NOUN_CONFIG_CACHE = {"mtime": None, "config": None}
_FILTER_WORDS_CACHE = {"mtime": None, "words": set()}
_SPACY_NLP_CACHE = {"model": None, "nlp": None, "failed_models": set()}
_CEFR_ANALYZER = {"loaded": False, "value": None}
_WORDFREQ_IMPORT = {"loaded": False, "func": None}
_IPA_CACHE = {}
_OLLAMA_REQUEST_LOCK = threading.Lock()


@dataclass
class AnnotationStats:
    words_seen: int = 0
    difficult_candidates: int = 0
    translated_words: int = 0
    inserted_annotations: int = 0
    ollama_requests: int = 0


def _config_mtime():
    return CONFIG_FILE.stat().st_mtime if CONFIG_FILE.exists() else None


def normalize_word(raw_word):
    return raw_word.strip().strip(".,!?;:\"()[]{}<>").replace("\u2019", "'")


def cefr_level_to_text(level):
    if level is None:
        return ""
    if hasattr(level, "name"):
        return str(level.name).upper()
    return str(level).strip().upper()


def parse_csv_levels(value, default):
    levels = {item.strip().upper() for item in str(value).split(",") if item.strip()}
    return levels or set(default)


def parse_csv_words(value):
    words = set()
    for item in str(value).split(","):
        for token in WORD_RE.findall(item):
            normalized = normalize_word(token).lower()
            if normalized:
                words.add(normalized)
    return words


def config_bool(section, section_name, key, default):
    try:
        return section.getboolean(key, fallback=default)
    except ValueError:
        logger.warning("Invalid %s.%s=%r, using default=%s", section_name, key, section.get(key), default)
        return default


def config_positive_int(section, section_name, key, default):
    try:
        return max(1, section.getint(key, fallback=default))
    except ValueError:
        logger.warning("Invalid %s.%s=%r, using default=%s", section_name, key, section.get(key), default)
        return max(1, int(default))


def config_nonnegative_float(section, section_name, key, default):
    try:
        return max(0.0, section.getfloat(key, fallback=default))
    except ValueError:
        logger.warning("Invalid %s.%s=%r, using default=%s", section_name, key, section.get(key), default)
        return max(0.0, float(default))


def load_difficulty_config():
    mtime = _config_mtime()
    cached = _DIFFICULTY_CONFIG_CACHE["config"]
    if cached is not None and _DIFFICULTY_CONFIG_CACHE["mtime"] == mtime:
        return cached

    config = dict(DEFAULT_DIFFICULTY_CONFIG)
    if CONFIG_FILE.exists():
        parser = configparser.ConfigParser()
        parser.read(CONFIG_FILE, encoding="utf-8")
        if parser.has_section("DifficultyConfig"):
            section = parser["DifficultyConfig"]
            config["advanced_levels"] = parse_csv_levels(
                section.get("AdvancedLevels", ",".join(sorted(config["advanced_levels"]))),
                config["advanced_levels"],
            )
            config["min_candidate_length"] = config_positive_int(
                section, "DifficultyConfig", "MinCandidateLength", config["min_candidate_length"]
            )
            config["b1_min_length"] = config_positive_int(
                section, "DifficultyConfig", "B1MinLength", config["b1_min_length"]
            )
            config["b1_frequency_threshold"] = config_nonnegative_float(
                section, "DifficultyConfig", "B1FrequencyThreshold", config["b1_frequency_threshold"]
            )
            config["b2_min_length"] = config_positive_int(
                section, "DifficultyConfig", "B2MinLength", config["b2_min_length"]
            )
            config["b2_frequency_threshold"] = config_nonnegative_float(
                section, "DifficultyConfig", "B2FrequencyThreshold", config["b2_frequency_threshold"]
            )
            config["unknown_min_length"] = config_positive_int(
                section, "DifficultyConfig", "UnknownMinLength", config["unknown_min_length"]
            )
            config["unknown_frequency_threshold"] = config_nonnegative_float(
                section, "DifficultyConfig", "UnknownFrequencyThreshold", config["unknown_frequency_threshold"]
            )

    logger.info(
        "Difficulty config: advanced=%s min_len=%s B1(len>=%s,freq<%s) B2(len>=%s,freq<%s) unknown(len>=%s,freq<%s)",
        ",".join(sorted(config["advanced_levels"])),
        config["min_candidate_length"],
        config["b1_min_length"],
        config["b1_frequency_threshold"],
        config["b2_min_length"],
        config["b2_frequency_threshold"],
        config["unknown_min_length"],
        config["unknown_frequency_threshold"],
    )
    _DIFFICULTY_CONFIG_CACHE["mtime"] = mtime
    _DIFFICULTY_CONFIG_CACHE["config"] = config
    return config


def load_translation_config():
    mtime = _config_mtime()
    cached = _TRANSLATION_CONFIG_CACHE["config"]
    if cached is not None and _TRANSLATION_CONFIG_CACHE["mtime"] == mtime:
        return cached

    config = dict(DEFAULT_TRANSLATION_CONFIG)
    if CONFIG_FILE.exists():
        parser = configparser.ConfigParser()
        parser.read(CONFIG_FILE, encoding="utf-8")
        if parser.has_section("TranslationConfig"):
            section = parser["TranslationConfig"]
            config["segments_per_translation"] = config_positive_int(
                section, "TranslationConfig", "SegmentsPerTranslation", config["segments_per_translation"]
            )
            config["use_context_meaning"] = config_bool(
                section, "TranslationConfig", "UseContextMeaning", config["use_context_meaning"]
            )
            config["max_meaning_chars"] = config_positive_int(
                section, "TranslationConfig", "MaxMeaningChars", config["max_meaning_chars"]
            )
            config["retry_on_verbose_meaning"] = config_bool(
                section, "TranslationConfig", "RetryOnVerboseMeaning", config["retry_on_verbose_meaning"]
            )
            policy = section.get("AmbiguousMeaningPolicy", config["ambiguous_meaning_policy"]).strip().lower()
            if policy not in {"skip"}:
                logger.warning("Invalid TranslationConfig.AmbiguousMeaningPolicy=%r, using skip", policy)
                policy = "skip"
            config["ambiguous_meaning_policy"] = policy
            config["ollama_temperature"] = config_nonnegative_float(
                section, "TranslationConfig", "OllamaTemperature", config["ollama_temperature"]
            )
            config["ollama_model"] = section.get("OllamaModel", config["ollama_model"]).strip() or config["ollama_model"]
            config["repeat_window_words"] = config_positive_int(
                section, "TranslationConfig", "TranslationRepeatWindowWords", config["repeat_window_words"]
            )
            config["translation_batch_size"] = config_positive_int(
                section, "TranslationConfig", "TranslationBatchSize", config["translation_batch_size"]
            )
            config["max_context_chars"] = config_positive_int(
                section, "TranslationConfig", "MaxContextChars", config["max_context_chars"]
            )
            config["ollama_timeout_seconds"] = config_positive_int(
                section, "TranslationConfig", "OllamaTimeoutSeconds", config["ollama_timeout_seconds"]
            )
            config["ollama_request_retries"] = config_positive_int(
                section, "TranslationConfig", "OllamaRequestRetries", config["ollama_request_retries"]
            )
            config["ollama_retry_sleep_seconds"] = config_positive_int(
                section, "TranslationConfig", "OllamaRetrySleepSeconds", config["ollama_retry_sleep_seconds"]
            )
            config["ipa_provider"] = section.get("IpaProvider", config["ipa_provider"]).strip().lower() or "auto"

    env_model = os.getenv("BOOKVOCAB_OLLAMA_MODEL")
    if env_model:
        config["ollama_model"] = env_model.strip() or config["ollama_model"]

    logger.info(
        "Translation config: model=%s batch=%s repeat_window_words=%s max_meaning_chars=%s "
        "max_context_chars=%s timeout=%ss request_retries=%s",
        config["ollama_model"],
        config["translation_batch_size"],
        config["repeat_window_words"],
        config["max_meaning_chars"],
        config["max_context_chars"],
        config["ollama_timeout_seconds"],
        config["ollama_request_retries"],
    )
    _TRANSLATION_CONFIG_CACHE["mtime"] = mtime
    _TRANSLATION_CONFIG_CACHE["config"] = config
    return config


def load_proper_noun_config():
    mtime = _config_mtime()
    cached = _PROPER_NOUN_CONFIG_CACHE["config"]
    if cached is not None and _PROPER_NOUN_CONFIG_CACHE["mtime"] == mtime:
        return cached

    config = {
        "enabled": DEFAULT_PROPER_NOUN_CONFIG["enabled"],
        "model": DEFAULT_PROPER_NOUN_CONFIG["model"],
        "entity_labels": set(DEFAULT_PROPER_NOUN_CONFIG["entity_labels"]),
        "skip_words": set(DEFAULT_PROPER_NOUN_CONFIG["skip_words"]),
    }
    if CONFIG_FILE.exists():
        parser = configparser.ConfigParser()
        parser.read(CONFIG_FILE, encoding="utf-8")
        if parser.has_section("ProperNounConfig"):
            section = parser["ProperNounConfig"]
            config["enabled"] = config_bool(section, "ProperNounConfig", "SkipProperNouns", config["enabled"])
            config["model"] = section.get("NlpModel", config["model"]).strip() or config["model"]
            config["entity_labels"] = parse_csv_levels(
                section.get("EntityLabels", ",".join(sorted(config["entity_labels"]))),
                config["entity_labels"],
            )
            config["skip_words"] = parse_csv_words(section.get("SkipWords", ""))

    logger.info(
        "Proper noun config: enabled=%s model=%s labels=%s skip_words=%d",
        config["enabled"],
        config["model"],
        ",".join(sorted(config["entity_labels"])),
        len(config["skip_words"]),
    )
    _PROPER_NOUN_CONFIG_CACHE["mtime"] = mtime
    _PROPER_NOUN_CONFIG_CACHE["config"] = config
    return config


def load_filter_words():
    if not FILTER_FILE.exists():
        return set()

    mtime = FILTER_FILE.stat().st_mtime
    if _FILTER_WORDS_CACHE["mtime"] == mtime:
        return _FILTER_WORDS_CACHE["words"]

    words = set()
    for line in FILTER_FILE.read_text(encoding="utf-8", errors="ignore").splitlines():
        candidate = re.sub(r"^[-*+]\s*", "", line.strip())
        if not candidate or candidate.startswith("#"):
            continue
        token = candidate.split()[0]
        normalized = normalize_word(token).lower()
        if normalized:
            words.add(normalized)

    logger.info("Loaded %d filter words from %s", len(words), FILTER_FILE)
    _FILTER_WORDS_CACHE["mtime"] = mtime
    _FILTER_WORDS_CACHE["words"] = words
    return words


def get_cefr_analyzer():
    if _CEFR_ANALYZER["loaded"]:
        return _CEFR_ANALYZER["value"]
    _CEFR_ANALYZER["loaded"] = True
    try:
        from cefrpy import CEFRAnalyzer

        _CEFR_ANALYZER["value"] = CEFRAnalyzer()
        logger.info("Loaded cefrpy CEFRAnalyzer")
    except Exception as exc:
        logger.warning("cefrpy is unavailable; difficulty detection falls back to word length/frequency: %s", exc)
        _CEFR_ANALYZER["value"] = None
    return _CEFR_ANALYZER["value"]


def get_word_frequency(word):
    if not _WORDFREQ_IMPORT["loaded"]:
        _WORDFREQ_IMPORT["loaded"] = True
        try:
            from wordfreq import word_frequency

            _WORDFREQ_IMPORT["func"] = word_frequency
            logger.info("Loaded wordfreq.word_frequency")
        except Exception as exc:
            logger.warning("wordfreq is unavailable; unknown long words are treated as rare: %s", exc)
            _WORDFREQ_IMPORT["func"] = None

    if _WORDFREQ_IMPORT["func"] is None:
        return 0.0
    return _WORDFREQ_IMPORT["func"](word, "en")


def get_spacy_nlp(model_name):
    if _SPACY_NLP_CACHE["model"] == model_name and _SPACY_NLP_CACHE["nlp"] is not None:
        return _SPACY_NLP_CACHE["nlp"]
    if model_name in _SPACY_NLP_CACHE["failed_models"]:
        return None

    try:
        import spacy
    except ImportError:
        logger.warning("spaCy is not installed; proper noun filtering is disabled")
        _SPACY_NLP_CACHE["failed_models"].add(model_name)
        return None

    try:
        nlp = spacy.load(model_name, disable=["tagger", "parser", "attribute_ruler", "lemmatizer"])
    except Exception as exc:
        logger.warning("spaCy model %s is unavailable; proper noun filtering is disabled: %s", model_name, exc)
        _SPACY_NLP_CACHE["failed_models"].add(model_name)
        return None

    _SPACY_NLP_CACHE["model"] = model_name
    _SPACY_NLP_CACHE["nlp"] = nlp
    logger.info("Loaded spaCy NER model=%s pipes=%s", model_name, ",".join(nlp.pipe_names))
    return nlp


def find_proper_noun_words(english_text):
    config = load_proper_noun_config()
    words = set(config["skip_words"])
    if not config["enabled"] or not english_text.strip():
        return words

    nlp = get_spacy_nlp(config["model"])
    if nlp is None:
        return words

    try:
        doc = nlp(english_text[:100000])
    except Exception:
        logger.exception("spaCy proper noun detection failed; using configured SkipWords only")
        return words

    entity_words = set()
    for entity in doc.ents:
        if entity.label_.upper() not in config["entity_labels"]:
            continue
        for token in WORD_RE.findall(entity.text):
            normalized = normalize_word(token).lower()
            if normalized:
                entity_words.add(normalized)
    words.update(entity_words)
    return words


def is_acronym_or_tool_name(raw_word, filter_words=None, difficulty_config=None):
    if difficulty_config is None:
        difficulty_config = load_difficulty_config()

    word = normalize_word(raw_word)
    if not word:
        return True

    compact = word.replace("-", "").replace("_", "").replace(".", "").replace("'", "")
    lower = compact.lower()
    if filter_words and lower in filter_words:
        return True
    if lower in SKIP_WORDS:
        return True
    if len(compact) < difficulty_config["min_candidate_length"]:
        return True
    if compact.isupper() and compact.isalpha():
        return True
    if any(ch.isdigit() for ch in compact):
        return True

    has_lower = any(ch.islower() for ch in compact)
    has_upper = any(ch.isupper() for ch in compact)
    is_normal_title_case = len(compact) > 1 and compact[0].isupper() and compact[1:].islower()
    if has_lower and has_upper and not is_normal_title_case:
        return True

    return False


def is_difficult(word, filter_words=None, difficulty_config=None):
    if difficulty_config is None:
        difficulty_config = load_difficulty_config()

    word = normalize_word(word)
    clean_word = word.lower()
    if not clean_word.isalpha():
        return False
    if is_acronym_or_tool_name(word, filter_words=filter_words, difficulty_config=difficulty_config):
        return False

    analyzer = get_cefr_analyzer()
    level = ""
    if analyzer is not None:
        try:
            level = cefr_level_to_text(analyzer.get_average_word_level_CEFR(clean_word))
        except Exception:
            logger.exception("CEFR lookup failed for word=%s", clean_word)

    freq = get_word_frequency(clean_word)
    if level in difficulty_config["advanced_levels"]:
        return True
    if level == "B2" and len(clean_word) >= difficulty_config["b2_min_length"]:
        return freq < difficulty_config["b2_frequency_threshold"]
    if level == "B1" and len(clean_word) >= difficulty_config["b1_min_length"]:
        return freq < difficulty_config["b1_frequency_threshold"]
    if not level and len(clean_word) >= difficulty_config["unknown_min_length"]:
        return freq < difficulty_config["unknown_frequency_threshold"]
    return False


def extract_json_payload(text):
    stripped = str(text or "").strip()
    stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
    stripped = re.sub(r"\s*```$", "", stripped)
    start = stripped.find("[")
    end = stripped.rfind("]")
    if start != -1 and end != -1 and end > start:
        return stripped[start:end + 1]
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end != -1 and end > start:
        return stripped[start:end + 1]
    return stripped


def parse_translation_json(response_text):
    payload = extract_json_payload(response_text)
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return None

    if isinstance(data, dict) and isinstance(data.get("translations"), list):
        data = data["translations"]

    mapping = {}
    if isinstance(data, dict):
        for word, meaning in data.items():
            normalized = normalize_word(str(word)).lower()
            if normalized:
                mapping[normalized] = "" if meaning is None else str(meaning).strip()
        return mapping

    if isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            word = normalize_word(str(item.get("word", ""))).lower()
            meaning = item.get("meaning", "")
            if word:
                mapping[word] = "" if meaning is None else str(meaning).strip()
        return mapping
    return None


def meaning_char_count(meaning):
    return len(re.sub(r"\s+", "", str(meaning or "")))


def normalize_context_meaning(meaning, max_chars):
    value = str(meaning or "").strip()
    lowered = value.lower()
    if lowered in {"", "skip", "[skip]", "none", "n/a", "na", "unclear", "unknown"}:
        return "", "skip"
    if meaning_char_count(value) > 20:
        return "", "skip verbose meaning"
    if any(separator in value for separator in (";", "；", "、", "/", "|", "\n", "，", ",")):
        value = re.split(r"[;；、/|\n，,]+", value, maxsplit=1)[0].strip()
    if ":" in value or "：" in value:
        return None, "contains nested label"
    if meaning_char_count(value) > max_chars:
        return None, f"exceeds {max_chars} chars"
    return value, ""


def parse_context_translation_response(response_text, expected_words, max_chars):
    parsed = parse_translation_json(response_text)
    if parsed is None:
        return {}, set(expected_words), set()

    valid = {}
    invalid = set()
    skipped = set()
    for word in expected_words:
        meaning, reason = normalize_context_meaning(parsed.get(word, ""), max_chars)
        if meaning is None:
            invalid.add(word)
            logger.warning("Invalid meaning word=%s reason=%s raw=%r", word, reason, parsed.get(word, ""))
        elif meaning:
            valid[word] = meaning
        else:
            skipped.add(word)
    return valid, invalid, skipped


def build_context_translation_prompt(unique_words, context_text, max_chars, strict_retry=False):
    strict_line = "Previous output was invalid. Return JSON only.\n" if strict_retry else ""
    return (
        "You are translating English vocabulary for Chinese learners.\n"
        f"{strict_line}"
        "Use the context to choose the single best Simplified Chinese meaning for each word.\n"
        f"Each Chinese meaning must be {max_chars} Chinese characters or fewer.\n"
        "Return one concise meaning only. Do not list alternatives. Do not explain.\n"
        "Do not translate person names, place names, organizations, brand names, or fictional proper nouns.\n"
        "If the meaning is unclear from context, use an empty string.\n\n"
        f"Context:\n{context_text}\n\n"
        f"Words:\n{json.dumps(unique_words, ensure_ascii=False)}\n\n"
        'Return JSON only: [{"word":"example","meaning":"例子"}]'
    )


def call_ollama(prompt, translation_config):
    try:
        import requests
    except Exception as exc:
        logger.error("requests is unavailable; cannot call Ollama: %s", exc)
        return ""

    payload = {
        "model": translation_config["ollama_model"],
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": translation_config["ollama_temperature"]},
    }
    retries = max(1, int(translation_config.get("ollama_request_retries", 1)))
    sleep_seconds = max(0, int(translation_config.get("ollama_retry_sleep_seconds", 0)))
    last_exc = None

    for attempt in range(1, retries + 1):
        try:
            with _OLLAMA_REQUEST_LOCK:
                response = requests.post(
                    OLLAMA_API,
                    json=payload,
                    timeout=translation_config["ollama_timeout_seconds"],
                )
            response.raise_for_status()
            return response.json().get("response", "").strip()
        except Exception as exc:
            last_exc = exc
            if attempt < retries:
                logger.warning(
                    "Ollama request failed model=%s attempt=%d/%d: %s",
                    translation_config["ollama_model"],
                    attempt,
                    retries,
                    exc,
                )
                if sleep_seconds:
                    time.sleep(sleep_seconds)

    raise last_exc if last_exc is not None else RuntimeError("Ollama request failed")


def trim_context(text, max_chars):
    compact = " ".join(str(text or "").split())
    if len(compact) <= max_chars:
        return compact
    half = max(1, max_chars // 2)
    return compact[:half] + "\n...\n" + compact[-half:]


def chunked(values, size):
    for index in range(0, len(values), size):
        yield values[index:index + size]


def translate_words_mapping(words_list, context_text="", filter_words=None, stats=None):
    translation_config = load_translation_config()
    difficulty_config = load_difficulty_config()
    unique_words = []
    seen = set()
    for word in words_list:
        normalized = normalize_word(word).lower()
        if not normalized or normalized in seen:
            continue
        if is_acronym_or_tool_name(normalized, filter_words=filter_words, difficulty_config=difficulty_config):
            continue
        unique_words.append(normalized)
        seen.add(normalized)

    if not unique_words:
        return {}

    max_chars = translation_config["max_meaning_chars"]
    attempts = 2 if translation_config["retry_on_verbose_meaning"] else 1
    context = trim_context(context_text, translation_config["max_context_chars"])
    final_meanings = {}

    def translate_batch(batch_words, strict_depth=0):
        if not batch_words:
            return {}

        local_result = {}
        remaining_words = list(batch_words)
        for attempt in range(1, attempts + 1):
            if not remaining_words:
                break
            prompt = build_context_translation_prompt(
                remaining_words,
                context if translation_config["use_context_meaning"] else "",
                max_chars,
                strict_retry=attempt > 1,
            )
            try:
                if stats is not None:
                    stats.ollama_requests += 1
                logger.info(
                    "Ollama translation model=%s words=%d attempt=%d/%d",
                    translation_config["ollama_model"],
                    len(remaining_words),
                    attempt,
                    attempts,
                )
                response_text = call_ollama(prompt, translation_config)
            except Exception as exc:
                if len(remaining_words) > 1:
                    midpoint = len(remaining_words) // 2
                    logger.warning(
                        "Ollama request failed for %d word(s); splitting batch and retrying: %s",
                        len(remaining_words),
                        exc,
                    )
                    left = translate_batch(remaining_words[:midpoint], strict_depth + 1)
                    right = translate_batch(remaining_words[midpoint:], strict_depth + 1)
                    local_result.update(left)
                    local_result.update(right)
                else:
                    logger.warning("Ollama request failed for word=%s; skipping: %s", remaining_words[0], exc)
                return local_result

            valid, invalid, skipped = parse_context_translation_response(response_text, remaining_words, max_chars)
            local_result.update(valid)
            if skipped:
                logger.info("Skipped unclear meanings: %s", ", ".join(sorted(skipped)))
            if invalid and attempt < attempts:
                logger.warning("Retrying invalid meanings: %s", ", ".join(sorted(invalid)))
                remaining_words = sorted(invalid)
                continue
            if invalid:
                if len(invalid) == len(remaining_words) and len(remaining_words) > 1:
                    midpoint = len(remaining_words) // 2
                    logger.warning(
                        "Invalid meanings for all %d words; splitting batch and retrying smaller groups",
                        len(remaining_words),
                    )
                    left = translate_batch(remaining_words[:midpoint], strict_depth + 1)
                    right = translate_batch(remaining_words[midpoint:], strict_depth + 1)
                    local_result.update(left)
                    local_result.update(right)
                    return local_result
                logger.warning("Skipping invalid meanings after retry: %s", ", ".join(sorted(invalid)))
            break

        return local_result

    for batch in chunked(unique_words, translation_config["translation_batch_size"]):
        final_meanings.update(translate_batch(list(batch)))

    return {word: final_meanings[word] for word in unique_words if word in final_meanings}


ARPABET_TO_IPA = {
    "AA": "ɑ", "AE": "æ", "AH": "ə", "AO": "ɔ", "AW": "aʊ", "AY": "aɪ", "B": "b",
    "CH": "tʃ", "D": "d", "DH": "ð", "EH": "ɛ", "ER": "ɝ", "EY": "eɪ", "F": "f",
    "G": "ɡ", "HH": "h", "IH": "ɪ", "IY": "i", "JH": "dʒ", "K": "k", "L": "l",
    "M": "m", "N": "n", "NG": "ŋ", "OW": "oʊ", "OY": "ɔɪ", "P": "p", "R": "r",
    "S": "s", "SH": "ʃ", "T": "t", "TH": "θ", "UH": "ʊ", "UW": "u", "V": "v",
    "W": "w", "Y": "j", "Z": "z", "ZH": "ʒ",
}


def clean_ipa(value, word):
    ipa = str(value or "").strip().strip("/").strip()
    ipa = ipa.replace("*", "").strip()
    ipa = re.sub(r"\s+", " ", ipa)
    if not ipa or ipa.lower() == word.lower():
        return ""
    if any(ch in ipa for ch in "[]{}<>"):
        return ""
    if len(ipa) > 60:
        return ""
    return ipa


def ipa_from_eng_to_ipa(word):
    try:
        import eng_to_ipa as eng_ipa

        return clean_ipa(eng_ipa.convert(word), word)
    except Exception:
        return ""


def ipa_from_pronouncing(word):
    try:
        import pronouncing
    except Exception:
        return ""

    phones = pronouncing.phones_for_word(word)
    if not phones:
        return ""

    pieces = []
    for token in phones[0].split():
        stress = token[-1] if token[-1].isdigit() else ""
        base = token[:-1] if stress else token
        ipa = ARPABET_TO_IPA.get(base, "")
        if not ipa:
            continue
        if stress == "1":
            ipa = "ˈ" + ipa
        elif stress == "2":
            ipa = "ˌ" + ipa
        pieces.append(ipa)
    return clean_ipa("".join(pieces), word)


def ipa_from_ollama(word, stats=None):
    translation_config = load_translation_config()
    prompt = (
        "Return only the IPA pronunciation for this English word.\n"
        "Do not include slashes, brackets, explanations, alternatives, or Chinese.\n\n"
        f"Word: {word}"
    )
    try:
        if stats is not None:
            stats.ollama_requests += 1
        response_text = call_ollama(prompt, translation_config)
    except Exception as exc:
        logger.warning("Ollama IPA fallback failed for %s: %s", word, exc)
        return ""
    return clean_ipa(response_text, word)


def get_ipa(word, stats=None):
    normalized = normalize_word(word).lower()
    if not normalized:
        return ""
    if normalized in _IPA_CACHE:
        return _IPA_CACHE[normalized]

    translation_config = load_translation_config()
    provider = translation_config["ipa_provider"]
    ipa = ""
    if provider in {"auto", "eng_to_ipa"}:
        ipa = ipa_from_eng_to_ipa(normalized)
    if not ipa and provider in {"auto", "pronouncing"}:
        ipa = ipa_from_pronouncing(normalized)
    if not ipa and provider in {"auto", "ollama"}:
        ipa = ipa_from_ollama(normalized, stats=stats)

    if not ipa:
        logger.warning("IPA unavailable for word=%s; using placeholder", normalized)
        ipa = "?"

    _IPA_CACHE[normalized] = ipa
    return ipa


class VocabularyAnnotator:
    def __init__(self):
        self.filter_words = load_filter_words()
        self.difficulty_config = load_difficulty_config()
        self.translation_config = load_translation_config()
        self.recent_translations = {}
        self.word_index = 0
        self.stats = AnnotationStats()

    def _eligible_spans(self, text):
        proper_words = find_proper_noun_words(text)
        combined_filter_words = set(self.filter_words)
        combined_filter_words.update(proper_words)

        local_recent = dict(self.recent_translations)
        spans = []
        for match in WORD_RE.finditer(text):
            original = match.group(0)
            normalized = normalize_word(original).lower()
            self.word_index += 1
            self.stats.words_seen += 1
            if not normalized:
                continue

            last_position = local_recent.get(normalized)
            if last_position is not None and 0 <= self.word_index - last_position <= self.translation_config["repeat_window_words"]:
                continue

            if is_difficult(original, filter_words=combined_filter_words, difficulty_config=self.difficulty_config):
                spans.append(
                    {
                        "start": match.start(),
                        "end": match.end(),
                        "word": original,
                        "normalized": normalized,
                        "position": self.word_index,
                    }
                )
                local_recent[normalized] = self.word_index
                self.stats.difficult_candidates += 1

        return spans, combined_filter_words

    def annotate_text(self, text):
        if not text or not WORD_RE.search(text):
            return text

        spans, combined_filter_words = self._eligible_spans(text)
        if not spans:
            return text

        unique_words = []
        seen = set()
        for span in spans:
            if span["normalized"] not in seen:
                unique_words.append(span["normalized"])
                seen.add(span["normalized"])

        translated = translate_words_mapping(
            unique_words,
            context_text=text,
            filter_words=combined_filter_words,
            stats=self.stats,
        )
        if not translated:
            return text

        span_lookup = {}
        for span in spans:
            meaning = translated.get(span["normalized"])
            if not meaning:
                continue
            ipa = get_ipa(span["normalized"], stats=self.stats)
            span_lookup[(span["start"], span["end"])] = (ipa, meaning)
            self.recent_translations[span["normalized"]] = span["position"]
            self.stats.translated_words += 1

        if not span_lookup:
            return text

        def replace(match):
            key = (match.start(), match.end())
            entry = span_lookup.get(key)
            if not entry:
                return match.group(0)
            ipa, meaning = entry
            self.stats.inserted_annotations += 1
            return f"{match.group(0)} /{ipa}/[{meaning}]"

        return WORD_RE.sub(replace, text)
