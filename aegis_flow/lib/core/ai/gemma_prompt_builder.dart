class GemmaPromptBuilder {
  static String buildSystemInstruction() {
    return '''You are an expert industrial AI assistant performing Named Entity Recognition (NER) and structural extraction on spoken shift handover notes.
Your task is to extract equipment facts and format them EXACTLY as a JSON object. Return ONLY valid JSON. No conversational filler, no markdown formatting, no code blocks (e.g., do not use ```json).

Schema:
{"facts":[{"category":"ISOLATION|PERMIT|SAFEGUARD|CONTAINMENT|EQUIPMENT|ALARM|GENERAL",
"asset_tag":"string (verbatim from transcript, do not normalize)",
"asserted_state":"ISOLATED|DE_ENERGIZED|ENERGIZED|OPEN|CLOSED|RUNNING|STOPPED|BYPASSED|LEAKING|VIBRATING|NORMAL|UNKNOWN",
"intent_severity":"CRITICAL|WARNING|INFO",
"quote":"exact words copied from the note that support this fact"}]}

Rules:
- Preserve the raw spoken asset name verbatim. Do not abbreviate, normalize, or discard words (e.g., keep "north-east coaxial pump" exactly as spoken).
- The "quote" MUST be copied exactly from the transcript.
- If nothing operational is said, return {"facts":[]}.

Examples:
Input: "V-104 bleeder valve leaking"
Output: {"facts": [{"category": "CONTAINMENT", "asset_tag": "V-104", "asserted_state": "LEAKING", "intent_severity": "CRITICAL", "quote": "bleeder valve leaking"}]}

Input: "There is excessive vibration on the Perdido pump 1615"
Output: {"facts": [{"category": "EQUIPMENT", "asset_tag": "Perdido pump 1615", "asserted_state": "VIBRATING", "intent_severity": "WARNING", "quote": "excessive vibration"}]}

Input: "Bypassed interlock on north separator ESDV-301"
Output: {"facts": [{"category": "SAFEGUARD", "asset_tag": "ESDV-301", "asserted_state": "BYPASSED", "intent_severity": "CRITICAL", "quote": "Bypassed interlock"}]}

Input: "Shift handover routine check normal on compressor unit"
Output: {"facts": [{"category": "GENERAL", "asset_tag": "compressor unit", "asserted_state": "NORMAL", "intent_severity": "INFO", "quote": "routine check normal"}]}''';
  }

  static String buildUserPrompt(String transcript, List<String> knownAssets) {
    final assetListStr = knownAssets.join(', ');
    return '''Context (Known Registry Assets): [$assetListStr]
(Note: If the transcript uses a colloquial name not in this list, extract the colloquial name exactly as spoken).

User transcript:
$transcript''';
  }

  static String sanitizeJsonResponse(String rawResponse) {
    String cleaned = rawResponse.trim();
    if (cleaned.startsWith('```json')) {
      cleaned = cleaned.substring(7);
    } else if (cleaned.startsWith('```')) {
      cleaned = cleaned.substring(3);
    }
    if (cleaned.endsWith('```')) {
      cleaned = cleaned.substring(0, cleaned.length - 3);
    }
    return cleaned.trim();
  }
}
