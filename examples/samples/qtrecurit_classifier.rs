//! LLM-based email classifier for recruitment emails.
//!
//! Uses `quanttide-agent` crate for LLM API calls.

use std::collections::HashMap;
use std::fs;

use quanttide_agent::llm::{CompleteOptions, LLM};
use quanttide_agent::message::Message;
use serde::{Deserialize, Serialize};
use serde_json::Value;

/// A single classification record stored in `.classification.json`.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Classification {
    pub message_id: String,
    pub classification: String,
    pub source: String,
    pub updated_at: String,
}

const CATEGORIES: &[&str] = &[
    "resume_submission",
    "interview_scheduling",
    "written_exam",
    "offer_letter",
    "hr_internal",
    "unrelated",
];

const SYSTEM_PROMPT: &str = "\
You are an email classifier for a recruitment system. \
Classify each email into exactly one category:
- resume_submission: Job applications, resumes, cover letters, internship applications
- interview_scheduling: Interview invitations, scheduling, confirmations
- written_exam: Coding tests, written exams, take-home assignments,笔试题目
- offer_letter: Offer letters, employment contracts, onboarding instructions
- hr_internal: Internal HR communications from company domain
- unrelated: Newsletters, notifications, spam, or anything not recruitment-related

Respond with ONLY a JSON array of objects, each with \"message_id\" and \"classification\" fields. \
Example:
[{\"message_id\": \"abc123\", \"classification\": \"resume_submission\"}, ...]";

// ── 分类文件 I/O ──────────────────────────────────────────────────

fn classification_path(base: &str, folder: &str) -> String {
    format!("{base}/{folder}.classification.json")
}

/// 从磁盘加载已有分类结果。
pub fn load_classifications(base: &str, folder: &str) -> HashMap<String, Classification> {
    let path = classification_path(base, folder);
    let content = match fs::read_to_string(&path) {
        Ok(c) => c,
        Err(_) => return HashMap::new(),
    };
    let list: Vec<Classification> = match serde_json::from_str(&content) {
        Ok(l) => l,
        Err(_) => return HashMap::new(),
    };
    list.into_iter()
        .map(|c| (c.message_id.clone(), c))
        .collect()
}

/// 保存分类结果到磁盘。
pub fn save_classifications(base: &str, folder: &str, classifications: &[Classification]) {
    let path = classification_path(base, folder);
    if let Ok(json) = serde_json::to_string_pretty(classifications) {
        fs::write(&path, json).ok();
    }
}

// ── 分类逻辑 ──────────────────────────────────────────────────────

/// 仅对尚未分类的邮件进行 LLM 分类。
pub fn classify_pending(
    msgs: &[Value],
    existing: &HashMap<String, Classification>,
    llm: &LLM,
) -> Vec<Classification> {
    let pending: Vec<&Value> = msgs
        .iter()
        .filter(|m| {
            m.get("message_id")
                .and_then(|id| id.as_str())
                .map(|id| !existing.contains_key(id))
                .unwrap_or(false)
        })
        .collect();

    if pending.is_empty() {
        return Vec::new();
    }

    let pending_owned: Vec<Value> = pending.into_iter().cloned().collect();

    // ponytail: 分批处理，每批最多 30 封
    let batch_size = 30;
    let mut all_results = Vec::new();
    for chunk in pending_owned.chunks(batch_size) {
        match classify_llm_batch(chunk, llm) {
            Ok(results) => {
                let now = chrono::Local::now().format("%Y-%m-%d %H:%M").to_string();
                for (mid, label) in results {
                    all_results.push(Classification {
                        message_id: mid,
                        classification: label,
                        source: "llm".to_string(),
                        updated_at: now.clone(),
                    });
                }
            }
            Err(e) => {
                eprintln!("  分类失败 (跳过): {e}");
            }
        }
    }
    all_results
}

/// 构建一封邮件的简短文本表示，用于 LLM prompt。
fn email_text(email: &Value) -> String {
    let subj = email.get("subject").and_then(|s| s.as_str()).unwrap_or("");
    let sender = email
        .get("head_from")
        .and_then(|hf| hf.as_object())
        .and_then(|o| o.get("mail_address"))
        .and_then(|m| m.as_str())
        .unwrap_or("");
    let body = email
        .get("body_plain_text")
        .or_else(|| email.get("body_preview"))
        .and_then(|b| b.as_str())
        .unwrap_or("");
    // ponytail: char-counting 避免 UTF-8 panic
    let body: &str = &if body.len() > 2000 {
        body.chars().take(2000).collect::<String>()
    } else {
        body.to_string()
    };
    format!("Subject: {subj}\nFrom: {sender}\n\nBody:\n{body}")
}

/// 剥离 markdown 代码块标记。
fn strip_fences(s: &str) -> &str {
    let s = s.trim();
    if let Some(inner) = s.strip_prefix("```json").or_else(|| s.strip_prefix("```")) {
        if let Some(end) = inner.rfind("```") {
            return inner[..end].trim();
        }
        return inner.trim();
    }
    s
}

/// 调用 LLM 分类一批邮件，返回 message_id → 分类标签 映射。
fn classify_llm_batch(msgs: &[Value], llm: &LLM) -> Result<HashMap<String, String>, String> {
    if msgs.is_empty() {
        return Ok(HashMap::new());
    }

    let mut user_content = String::from("Classify the following emails:\n\n");
    for (i, msg) in msgs.iter().enumerate() {
        let mid = msg.get("message_id").and_then(|m| m.as_str()).unwrap_or("");
        user_content.push_str(&format!("--- Email {} ---\n", i + 1));
        user_content.push_str(&format!("Message ID: {mid}\n"));
        user_content.push_str(&email_text(msg));
        user_content.push('\n');
    }

    let messages = vec![
        Message::new("system", SYSTEM_PROMPT),
        Message::new("user", &user_content),
    ];

    let options = CompleteOptions {
        temperature: Some(0.0),
        max_tokens: Some(4096),
        ..Default::default()
    };

    let resp = llm
        .complete(&messages, options)
        .map_err(|e| format!("LLM API 调用失败: {e}"))?;

    let content = strip_fences(&resp.content);

    let classifications: Vec<Value> =
        serde_json::from_str(content).map_err(|e| format!("LLM 输出不是有效的 JSON 数组: {e}"))?;

    let mut map = HashMap::new();
    for entry in &classifications {
        let mid = entry
            .get("message_id")
            .and_then(|m| m.as_str())
            .unwrap_or("");
        let label = entry
            .get("classification")
            .and_then(|c| c.as_str())
            .unwrap_or("unrelated")
            .to_lowercase();
        let label = if CATEGORIES.contains(&label.as_str()) {
            label
        } else {
            "unrelated".to_string()
        };
        map.insert(mid.to_string(), label);
    }
    Ok(map)
}
