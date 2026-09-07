# 交叉审查实验报告

LLM: DeepSeek Chat

度量方式: Token 级 Diff（去注释/去 docstring 后）

日期: 2026-07-03


## qtrecurit_classifier

- Token Diff: 87.01%（1119/1286 token 变更）

### 原始代码

```python
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
```

### 重写代码

```python
use std::collections::HashMap;
use std::fs;
use std::path::PathBuf;
use std::time::{SystemTime, UNIX_EPOCH};

use log::{error, warn};
use serde::{Deserialize, Serialize};
use serde_json::Value;

use quanttide_agent::LLM;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Classification {
    pub message_id: String,
    pub classification: String,
    pub source: String,
    pub updated_at: String,
}

const ALLOWED_CATEGORIES: &[&str] = &[
    "resume_submission",
    "interview_scheduling",
    "written_exam",
    "offer_letter",
    "hr_internal",
    "unrelated",
];

const BATCH_SIZE: usize = 30;
const MAX_BODY_LENGTH: usize = 2000;

pub fn classify_emails(
    msgs: &[Value],
    existing: &HashMap<String, Classification>,
    llm: &LLM,
    base: &str,
    folder: &str,
) -> Vec<Classification> {
    let mut new_classifications = Vec::new();

    // Filter out already classified emails
    let pending: Vec<&Value> = msgs
        .iter()
        .filter(|msg| {
            msg.get("message_id")
                .and_then(|v| v.as_str())
                .map(|id| !existing.contains_key(id))
                .unwrap_or(false)
        })
        .collect();

    if pending.is_empty() {
        return new_classifications;
    }

    // Process in batches
    for chunk in pending.chunks(BATCH_SIZE) {
        let batch: Vec<&Value> = chunk.to_vec();

        // Build LLM prompt
        let system_prompt = build_system_prompt();
        let user_prompt = build_user_prompt(&batch);

        // Call LLM
        let response = match llm.chat(&system_prompt, &user_prompt) {
            Ok(resp) => resp,
            Err(e) => {
                error!("LLM API call failed for batch: {}", e);
                continue;
            }
        };

        // Parse response
        let parsed = match parse_llm_response(&response) {
            Ok(map) => map,
            Err(e) => {
                warn!("Failed to parse LLM response for batch: {}", e);
                continue;
            }
        };

        // Create classification records
        let now = format_timestamp();
        for msg in &batch {
            let message_id = msg
                .get("message_id")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string();

            if message_id.is_empty() {
                continue;
            }

            let classification = parsed
                .get(&message_id)
                .cloned()
                .unwrap_or_else(|| "unrelated".to_string());

            let record = Classification {
                message_id: message_id.clone(),
                classification,
                source: "llm".to_string(),
                updated_at: now.clone(),
            };

            new_classifications.push(record);
        }
    }

    // Persist results
    let file_path = get_classification_path(base, folder);
    let mut all_classifications: Vec<Classification> = existing.values().cloned().collect();
    all_classifications.extend(new_classifications.clone());
    save_classifications(&file_path, &all_classifications);

    new_classifications
}

fn build_system_prompt() -> String {
    format!(
        r#"You are an email classifier for a recruitment system. Classify each email into exactly one of the following categories:

- resume_submission: Emails containing resumes, CVs, or job applications from candidates
- interview_scheduling: Emails about scheduling or confirming interviews
- written_exam: Emails about written tests or assessments
- offer_letter: Emails containing job offers or offer letters
- hr_internal: Internal HR communications about recruitment processes
- unrelated: Emails not related to recruitment

Respond with a JSON array of objects, each with "message_id" and "classification" fields.
Example: [{{"message_id": "abc123", "classification": "resume_submission"}}]"#
    )
}

fn build_user_prompt(emails: &[&Value]) -> String {
    let mut prompt = String::from("Classify the following emails:\n\n");

    for (i, email) in emails.iter().enumerate() {
        let message_id = email
            .get("message_id")
            .and_then(|v| v.as_str())
            .unwrap_or("unknown");

        let subject = email
            .get("subject")
            .and_then(|v| v.as_str())
            .unwrap_or("");

        let sender = email
            .get("head_from")
            .and_then(|v| v.get("mail_address"))
            .and_then(|v| v.as_str())
            .unwrap_or("");

        let body = email
            .get("body_plain_text")
            .or_else(|| email.get("body_preview"))
            .and_then(|v| v.as_str())
            .unwrap_or("");

        let truncated_body: String = body.chars().take(MAX_BODY_LENGTH).collect();

        prompt.push_str(&format!(
            "Email {}:\nID: {}\nSubject: {}\nFrom: {}\nBody: {}\n\n",
            i + 1,
            message_id,
            subject,
            sender,
            truncated_body
        ));
    }

    prompt.push_str("Return a JSON array of objects with message_id and classification fields.");
    prompt
}

fn parse_llm_response(response: &str) -> Result<HashMap<String, String>, String> {
    let cleaned = response
        .trim()
        .strip_prefix("
```

## qtrecurit_cli

- Token Diff: 21.76%（42/193 token 变更）

### 原始代码

```python
use clap::{Args, Parser, Subcommand};

use crate::status;

#[derive(Parser)]
#[command(name = "qtrecurit", version, about = "量潮招聘 CLI")]
pub struct Cli {
    #[command(subcommand)]
    pub command: Option<Commands>,
}

#[derive(Subcommand)]
pub enum Commands {
    /// 招聘数据统计（面向公开发文）
    Status(StatusArgs),
}

#[derive(Args)]
pub struct StatusArgs {
    /// 统计最近 N 天
    #[arg(long)]
    pub days: Option<u32>,
    /// 开始日期 (YYYY-MM-DD)
    #[arg(long)]
    pub start: Option<String>,
    /// 结束日期 (YYYY-MM-DD)
    #[arg(long)]
    pub end: Option<String>,
}

pub fn run() {
    let cli = Cli::parse();

    match &cli.command {
        Some(Commands::Status(args)) => {
            if let Err(e) = status::run(args) {
                eprintln!("错误: {}", e);
            }
        }
        None => {}
    }
}
```

### 重写代码

```python
use clap::{Parser, Subcommand};

#[derive(Parser)]
#[command(name = "qtrecurit")]
struct Cli {
    #[command(subcommand)]
    command: Option<Command>,
}

#[derive(Subcommand)]
enum Command {
    Status {
        /// Number of recent days to analyze
        #[arg(long)]
        days: Option<u32>,

        /// Start date in YYYY-MM-DD format
        #[arg(long)]
        start: Option<String>,

        /// End date in YYYY-MM-DD format
        #[arg(long)]
        end: Option<String>,
    },
}

pub fn run() {
    let cli = Cli::parse();

    match cli.command {
        Some(Command::Status { days, start, end }) => {
            if let Err(e) = crate::status::run(days, start, end) {
                eprintln!("错误: {}", e);
            }
        }
        None => {
            // Silent exit - no output
        }
    }
}
```

## qtrecurit_funnel

- Token Diff: 71.75%（772/1076 token 变更）

### 原始代码

```python
//! 招聘漏斗分析：投递 → 笔试 → 面试 → Offer

use crate::connect::email::MailItem;

/// 漏斗阶段
#[derive(Debug, Clone, Copy, Hash, PartialEq, Eq)]
pub enum Stage {
    /// 简历投递
    Resume,
    /// 笔试
    WrittenExam,
    /// 面试
    Interview,
    /// Offer
    Offer,
}

impl Stage {
    pub fn label(&self) -> &'static str {
        match self {
            Stage::Resume => "📥 投递",
            Stage::WrittenExam => "✍️ 笔试",
            Stage::Interview => "🎤 面试",
            Stage::Offer => "🎉 Offer",
        }
    }
}

/// 每封邮件的阶段判断结果
pub struct FunnelItem<'a> {
    pub item: &'a MailItem,
    pub stage: Option<Stage>,
}

/// 按主题关键词判断邮件所属阶段。
///
/// ponytail: 关键词匹配而非 LLM 分类——够用、零外部依赖。
/// 若需精细分类（按候选人聚合、去重），接入 classifier.rs 的 LLM 方案。
fn classify_stage(subject: &str) -> Option<Stage> {
    let s = subject.trim();
    if s.is_empty() {
        return None;
    }

    // 从上到下优先级递减，匹配即返回
    if s.contains("offer")
        || s.contains("Offer")
        || s.contains("录取")
        || s.contains("录用")
        || s.contains("入职")
    {
        return Some(Stage::Offer);
    }

    if s.contains("面试")
        || s.contains("面谈")
        || s.contains("interview")
        || s.contains("Interview")
    {
        return Some(Stage::Interview);
    }

    if s.contains("笔试")
        || s.contains("试题")
        || s.contains("作答")
        || s.contains("笔试题")
        || s.contains("written exam")
        || s.contains("Written Exam")
    {
        return Some(Stage::WrittenExam);
    }

    // 投递类关键字匹配（默认归类）
    if s.contains("简历")
        || s.contains("应聘")
        || s.contains("求职")
        || s.contains("申请")
        || s.contains("resume")
        || s.contains("Resume")
        || s.contains("application")
        || s.contains("Application")
        || s.contains("实习")
    {
        return Some(Stage::Resume);
    }

    // 匹配不上，可能不是招聘相关邮件
    None
}

/// 对邮件列表进行漏斗分析。
pub fn analyze(items: &[MailItem]) -> Vec<(Stage, usize)> {
    let mut counts: std::collections::HashMap<Stage, usize> = std::collections::HashMap::new();

    for item in items {
        if let Some(stage) = classify_stage(&item.subject) {
            *counts.entry(stage).or_insert(0) += 1;
        }
    }

    // 按漏斗顺序输出
    let order = [
        Stage::Resume,
        Stage::WrittenExam,
        Stage::Interview,
        Stage::Offer,
    ];
    order
        .iter()
        .map(|s| (*s, counts.get(s).copied().unwrap_or(0)))
        .collect()
}

/// 生成漏斗报告文本。
pub fn format_funnel(items: &[MailItem]) -> String {
    let stages = analyze(items);
    let max_count = stages.iter().map(|(_, c)| *c).max().unwrap_or(1).max(1);

    let mut out = String::new();
    out.push_str("## 招聘漏斗\n\n");
    out.push_str("| 阶段 | 数量 | 转化率 | 漏斗 |\n");
    out.push_str("|------|------|--------|------|\n");

    let mut prev: Option<usize> = None;
    for (stage, count) in stages {
        let bar_len = (count as f64 / max_count as f64 * 20.0).round() as usize;
        let bar = "█".repeat(bar_len);
        let conversion = match prev {
            Some(p) if p > 0 => format!("{:.0}%", count as f64 / p as f64 * 100.0),
            Some(_) => "—".to_string(),
            None => "—".to_string(),
        };
        out.push_str(&format!(
            "| {} | {} | {} | {} |\n",
            stage.label(),
            count,
            conversion,
            bar
        ));
        prev = Some(count);
    }

    out.push('\n');
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_classify_stage_resume() {
        assert_eq!(classify_stage("应聘全栈工程师"), Some(Stage::Resume));
        assert_eq!(classify_stage("求职 - 数据工程师"), Some(Stage::Resume));
        assert_eq!(classify_stage("实习申请"), Some(Stage::Resume));
    }

    #[test]
    fn test_classify_stage_written_exam() {
        assert_eq!(classify_stage("笔试题答案"), Some(Stage::WrittenExam));
        assert_eq!(
            classify_stage("【笔试】数据工程师试题"),
            Some(Stage::WrittenExam)
        );
    }

    #[test]
    fn test_classify_stage_interview() {
        assert_eq!(classify_stage("面试邀请 - 张三"), Some(Stage::Interview));
        assert_eq!(classify_stage("面试安排"), Some(Stage::Interview));
    }

    #[test]
    fn test_classify_stage_offer() {
        assert_eq!(classify_stage("Offer 确认"), Some(Stage::Offer));
        assert_eq!(classify_stage("录取通知"), Some(Stage::Offer));
        assert_eq!(classify_stage("入职指引"), Some(Stage::Offer));
    }

    #[test]
    fn test_classify_stage_priority() {
        // Offer 优先级最高
        assert_eq!(classify_stage("Offer 确认 - 面试通过"), Some(Stage::Offer));
        // 笔试高于默认投递
        assert_eq!(
            classify_stage("笔试题 - 应聘后端"),
            Some(Stage::WrittenExam)
        );
    }

    #[test]
    fn test_classify_stage_empty() {
        assert_eq!(classify_stage(""), None);
    }

    #[test]
    fn test_classify_stage_unrelated() {
        assert_eq!(classify_stage("自动回复：感谢您的邮件"), None);
        assert_eq!(classify_stage("新闻简报"), None);
    }

    #[test]
    fn test_analyze_empty() {
        let stages = analyze(&[]);
        // 返回 4 阶段，全部为 0
        assert_eq!(stages.len(), 4);
        assert!(stages.iter().all(|(_, c)| *c == 0));
    }

    #[test]
    fn test_analyze_mixed() {
        let items = vec![
            MailItem {
                subject: "应聘全栈工程师".into(),
                date: "2026-06-15".into(),
            },
            MailItem {
                subject: "应聘数据工程师".into(),
                date: "2026-06-15".into(),
            },
            MailItem {
                subject: "笔试题答案".into(),
                date: "2026-06-16".into(),
            },
            MailItem {
                subject: "面试邀请".into(),
                date: "2026-06-17".into(),
            },
            MailItem {
                subject: "Offer 确认".into(),
                date: "2026-06-18".into(),
            },
        ];
        let stages = analyze(&items);
        assert_eq!(stages.len(), 4);
        assert_eq!(stages[0], (Stage::Resume, 2));
        assert_eq!(stages[1], (Stage::WrittenExam, 1));
        assert_eq!(stages[2], (Stage::Interview, 1));
        assert_eq!(stages[3], (Stage::Offer, 1));
    }

    #[test]
    fn test_format_funnel_contains_header() {
        let items = vec![MailItem {
            subject: "应聘工程师".into(),
            date: "2026-06-15".into(),
        }];
        let output = format_funnel(&items);
        assert!(output.contains("招聘漏斗"));
        assert!(output.contains("投递"));
        assert!(output.contains("笔试"));
        assert!(output.contains("面试"));
        assert!(output.contains("Offer"));
    }

    #[test]
    fn test_format_funnel_empty() {
        let output = format_funnel(&[]);
        assert!(output.contains("招聘漏斗"));
        // All stages show 0
        assert!(output.contains("| 📥 投递 | 0 |"));
    }
}
```

### 重写代码

```python
use std::collections::HashMap;

/// Represents a recruitment email item.
pub struct MailItem {
    pub subject: String,
}

/// Represents a stage in the recruitment funnel.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum Stage {
    Resume,
    WrittenExam,
    Interview,
    Offer,
}

impl Stage {
    /// Returns all stages in funnel order.
    fn all() -> [Stage; 4] {
        [Stage::Resume, Stage::WrittenExam, Stage::Interview, Stage::Offer]
    }
}

/// Classifies an email subject into a recruitment stage.
/// Priority order: Offer > Interview > Written Exam > Resume.
/// Returns None for empty or unrelated subjects.
fn classify_stage(subject: &str) -> Option<Stage> {
    let subject = subject.trim();
    if subject.is_empty() {
        return None;
    }

    let lower = subject.to_lowercase();

    // Check in priority order (most advanced first)
    if lower.contains("offer") {
        return Some(Stage::Offer);
    }
    if lower.contains("interview") {
        return Some(Stage::Interview);
    }
    if lower.contains("written exam") || lower.contains("writtenexam") {
        return Some(Stage::WrittenExam);
    }
    if lower.contains("resume") || lower.contains("cv") {
        return Some(Stage::Resume);
    }

    None
}

/// Analyzes a slice of MailItems and returns counts per stage in funnel order.
/// Stages with zero count are included.
pub fn analyze(items: &[MailItem]) -> Vec<(Stage, usize)> {
    let mut counts: HashMap<Stage, usize> = HashMap::new();

    for item in items {
        if let Some(stage) = classify_stage(&item.subject) {
            *counts.entry(stage).or_insert(0) += 1;
        }
    }

    Stage::all()
        .iter()
        .map(|&stage| (stage, counts.get(&stage).copied().unwrap_or(0)))
        .collect()
}

/// Generates a Markdown table report with stage labels, counts, conversion rates,
/// and a 20-character bar visualization.
pub fn format_funnel(items: &[MailItem]) -> String {
    let results = analyze(items);
    let max_count = results.iter().map(|&(_, count)| count).max().unwrap_or(1);

    let mut output = String::new();
    output.push_str("| Stage | Count | Conversion | Bar |\n");
    output.push_str("|-------|-------|------------|-----|\n");

    let mut prev_count: Option<usize> = None;

    for (stage, count) in &results {
        let stage_label = match stage {
            Stage::Resume => "Resume",
            Stage::WrittenExam => "Written Exam",
            Stage::Interview => "Interview",
            Stage::Offer => "Offer",
        };

        // Conversion rate
        let conversion = match prev_count {
            None => "—".to_string(),
            Some(0) => "—".to_string(),
            Some(prev) => format!("{:.1}%", (*count as f64 / prev as f64) * 100.0),
        };

        // Bar visualization (20 chars max)
        let bar_len = if max_count == 0 {
            0
        } else {
            ((*count as f64 / max_count as f64) * 20.0).round() as usize
        };
        let bar = "█".repeat(bar_len);

        output.push_str(&format!("| {} | {} | {} | {} |\n", stage_label, count, conversion, bar));

        prev_count = Some(*count);
    }

    output
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_classify_stage() {
        assert_eq!(classify_stage("Offer: Senior Engineer"), Some(Stage::Offer));
        assert_eq!(classify_stage("Interview scheduled"), Some(Stage::Interview));
        assert_eq!(classify_stage("Written Exam results"), Some(Stage::WrittenExam));
        assert_eq!(classify_stage("Resume submitted"), Some(Stage::Resume));
        assert_eq!(classify_stage("CV attached"), Some(Stage::Resume));
        assert_eq!(classify_stage("Meeting reminder"), None);
        assert_eq!(classify_stage(""), None);
    }

    #[test]
    fn test_priority_classification() {
        // Should match Offer (highest priority)
        assert_eq!(
            classify_stage("Offer - Interview passed"),
            Some(Stage::Offer)
        );
        // Should match Interview (higher than Written Exam)
        assert_eq!(
            classify_stage("Interview - Written Exam done"),
            Some(Stage::Interview)
        );
    }

    #[test]
    fn test_analyze() {
        let items = vec![
            MailItem { subject: "Resume".to_string() },
            MailItem { subject: "Resume".to_string() },
            MailItem { subject: "Interview".to_string() },
            MailItem { subject: "Offer".to_string() },
            MailItem { subject: "Unrelated".to_string() },
        ];

        let result = analyze(&items);
        assert_eq!(result.len(), 4);
        assert_eq!(result[0], (Stage::Resume, 2));
        assert_eq!(result[1], (Stage::WrittenExam, 0));
        assert_eq!(result[2], (Stage::Interview, 1));
        assert_eq!(result[3], (Stage::Offer, 1));
    }

    #[test]
    fn test_format_funnel() {
        let items = vec![
            MailItem { subject: "Resume".to_string() },
            MailItem { subject: "Resume".to_string() },
            MailItem { subject: "Interview".to_string() },
            MailItem { subject: "Offer".to_string() },
        ];

        let report = format_funnel(&items);
        assert!(report.contains("| Stage | Count | Conversion | Bar |"));
        assert!(report.contains("| Resume | 2 | — |"));
        assert!(report.contains("| Written Exam | 0 | — |"));
        assert!(report.contains("| Interview | 1 | 50.0% |"));
        assert!(report.contains("| Offer | 1 | 100.0% |"));
    }
}
```

## qtrecurit_human_status

- Token Diff: 67.12%（978/1457 token 变更）

### 原始代码

```python
use anyhow::Result;
use serde::{Deserialize, Serialize};
use std::path::PathBuf;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RecruitmentPlan {
    pub month: String,
    pub positions: Vec<PositionPlan>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PositionPlan {
    pub name: String,
    pub headcount: u32,
    pub filled: u32,
    pub in_progress: u32,
    pub note: String,
}

pub fn default_plan() -> RecruitmentPlan {
    RecruitmentPlan {
        month: "2026-06".into(),
        positions: vec![
            PositionPlan { name: "数据工程师".into(), headcount: 2, filled: 0, in_progress: 0, note: "".into() },
            PositionPlan { name: "项目经理".into(), headcount: 1, filled: 0, in_progress: 0, note: "".into() },
            PositionPlan { name: "销售经理".into(), headcount: 1, filled: 0, in_progress: 0, note: "".into() },
            PositionPlan { name: "新媒体运营".into(), headcount: 1, filled: 0, in_progress: 0, note: "".into() },
            PositionPlan { name: "课程助教".into(), headcount: 1, filled: 0, in_progress: 0, note: "".into() },
            PositionPlan { name: "咨询助理".into(), headcount: 1, filled: 0, in_progress: 0, note: "".into() },
            PositionPlan { name: "商务经理".into(), headcount: 1, filled: 0, in_progress: 0, note: "".into() },
            PositionPlan { name: "执行助理".into(), headcount: 2, filled: 0, in_progress: 0, note: "".into() },
        ],
    }
}

pub trait PlanStore {
    fn load(&self) -> RecruitmentPlan;
}

pub struct FilePlanStore;

impl PlanStore for FilePlanStore {
    fn load(&self) -> RecruitmentPlan {
        let path = plan_path();
        if let Ok(content) = std::fs::read_to_string(&path) {
            if let Ok(plan) = serde_json::from_str(&content) {
                return plan;
            }
        }
        default_plan()
    }
}

fn plan_path() -> PathBuf {
    if let Ok(dir) = std::env::var("QTRECURIT_DATA") {
        let p = PathBuf::from(dir);
        return p.join("recruitment_plan.json");
    }
    if let Ok(dir) = std::env::var("QTRECURIT_CONFIG") {
        let p = PathBuf::from(dir);
        if let Some(parent) = p.parent() {
            return parent.join("recruitment_plan.json");
        }
    }
    if let Some(data_dir) = dirs::data_dir() {
        return data_dir.join("qtadmin").join("recruitment_plan.json");
    }
    if let Ok(cwd) = std::env::current_dir() {
        return cwd.join("recruitment_plan.json");
    }
    PathBuf::from("recruitment_plan.json")
}

pub fn format_status(store: &dyn PlanStore) -> String {
    let plan = store.load();
    let mut out = String::new();

    out.push_str(&format!("# {} 招聘计划与进度\n\n", plan.month));
    out.push_str("| 岗位 | 编制 | 已入职 | 进行中 | 备注 |\n");
    out.push_str("|------|------|--------|--------|------|\n");

    let mut total_headcount = 0u32;
    let mut total_filled = 0u32;
    let mut total_in_progress = 0u32;

    for p in &plan.positions {
        total_headcount += p.headcount;
        total_filled += p.filled;
        total_in_progress += p.in_progress;
        out.push_str(&format!("| {} | {} | {} | {} | {} |\n", p.name, p.headcount, p.filled, p.in_progress, p.note));
    }

    out.push('\n');
    out.push_str(&format!(
        "> 编制 {} 人 · 已入职 {} 人 · 进行中 {} 人 · 空缺 {} 人\n",
        total_headcount, total_filled, total_in_progress, total_headcount - total_filled
    ));
    out.push_str("> 截至 6 月 16 日\n");

    out
}

#[derive(clap::Args)]
pub struct StatusArgs;

pub fn run(_args: &StatusArgs, _provider: bool) -> Result<()> {
    let store = FilePlanStore;
    print!("{}", format_status(&store));
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    struct MockPlanStore {
        plan: RecruitmentPlan,
    }

    impl PlanStore for MockPlanStore {
        fn load(&self) -> RecruitmentPlan {
            self.plan.clone()
        }
    }

    #[test]
    fn test_format_status_contains_title() {
        let store = MockPlanStore { plan: default_plan() };
        let output = format_status(&store);
        assert!(output.contains("2026-06 招聘计划与进度"));
        assert!(output.contains("数据工程师"));
        assert!(output.contains("执行助理"));
    }

    #[test]
    fn test_format_status_totals() {
        let store = MockPlanStore { plan: default_plan() };
        let output = format_status(&store);
        assert!(output.contains("编制 10 人"));
        assert!(output.contains("空缺 10 人"));
    }

    #[test]
    fn test_format_status_with_partial_filled() {
        let plan = RecruitmentPlan {
            month: "2026-06".into(),
            positions: vec![
                PositionPlan { name: "数据工程师".into(), headcount: 2, filled: 1, in_progress: 1, note: "试用期".into() },
            ],
        };
        let store = MockPlanStore { plan };
        let output = format_status(&store);
        assert!(output.contains("数据工程师 | 2 | 1 | 1 | 试用期"));
        assert!(output.contains("编制 2 人 · 已入职 1 人 · 进行中 1 人 · 空缺 1 人"));
    }

    #[test]
    fn test_default_plan_not_empty() {
        let plan = default_plan();
        assert_eq!(plan.month, "2026-06");
        assert_eq!(plan.positions.len(), 8);
    }

    #[test]
    fn test_format_status_with_filled() {
        let plan = RecruitmentPlan {
            month: "2026-06".into(),
            positions: vec![
                PositionPlan { name: "数据工程师".into(), headcount: 2, filled: 1, in_progress: 1, note: "试用期".into() },
            ],
        };
        let store = MockPlanStore { plan };
        let output = format_status(&store);
        assert!(output.contains("1 | 1 | 试用期"));
        assert!(output.contains("编制 2 人 · 已入职 1 人"));
    }

    #[test]
    fn test_format_status_empty_positions() {
        let plan = RecruitmentPlan {
            month: "2026-06".into(),
            positions: vec![],
        };
        let store = MockPlanStore { plan };
        let output = format_status(&store);
        assert!(output.contains("编制 0 人"));
    }

    #[test]
    fn test_format_status_with_multiple_notes() {
        let plan = RecruitmentPlan {
            month: "2026-06".into(),
            positions: vec![
                PositionPlan { name: "全栈工程师".into(), headcount: 1, filled: 0, in_progress: 0, note: "急招".into() },
                PositionPlan { name: "数据工程师".into(), headcount: 2, filled: 2, in_progress: 0, note: "已满".into() },
            ],
        };
        let store = MockPlanStore { plan };
        let output = format_status(&store);
        assert!(output.contains("全栈工程师 | 1 | 0 | 0 | 急招"));
        assert!(output.contains("数据工程师 | 2 | 2 | 0 | 已满"));
    }
}
```

### 重写代码

```python
use anyhow::{Context, Result};
use clap::Parser;
use serde::{Deserialize, Serialize};
use std::fs;
use std::path::{Path, PathBuf};

/// Represents a monthly recruitment plan
#[derive(Debug, Serialize, Deserialize)]
pub struct RecruitmentPlan {
    pub month: String, // Format: "YYYY-MM"
    pub positions: Vec<PositionPlan>,
}

/// Per-position tracking data
#[derive(Debug, Serialize, Deserialize)]
pub struct PositionPlan {
    pub name: String,
    pub headcount: u32,
    pub filled: u32,
    pub in_progress: u32,
    pub notes: String,
}

/// CLI arguments (currently empty, reserved for future use)
#[derive(Parser, Debug)]
pub struct StatusArgs {
    /// Provider flag (unused)
    #[arg(long)]
    pub provider: Option<String>,
}

/// Generates a default plan for June 2026 with 8 positions
pub fn default_plan() -> RecruitmentPlan {
    RecruitmentPlan {
        month: "2026-06".to_string(),
        positions: vec![
            PositionPlan {
                name: "高级后端工程师".to_string(),
                headcount: 3,
                filled: 1,
                in_progress: 1,
                notes: "重点岗位".to_string(),
            },
            PositionPlan {
                name: "前端工程师".to_string(),
                headcount: 2,
                filled: 0,
                in_progress: 2,
                notes: "".to_string(),
            },
            PositionPlan {
                name: "产品经理".to_string(),
                headcount: 1,
                filled: 1,
                in_progress: 0,
                notes: "已到岗".to_string(),
            },
            PositionPlan {
                name: "测试工程师".to_string(),
                headcount: 2,
                filled: 1,
                in_progress: 0,
                notes: "".to_string(),
            },
            PositionPlan {
                name: "运维工程师".to_string(),
                headcount: 1,
                filled: 0,
                in_progress: 1,
                notes: "面试中".to_string(),
            },
            PositionPlan {
                name: "数据分析师".to_string(),
                headcount: 2,
                filled: 0,
                in_progress: 0,
                notes: "新岗位".to_string(),
            },
            PositionPlan {
                name: "UI设计师".to_string(),
                headcount: 1,
                filled: 1,
                in_progress: 0,
                notes: "".to_string(),
            },
            PositionPlan {
                name: "HRBP".to_string(),
                headcount: 1,
                filled: 0,
                in_progress: 1,
                notes: "待终面".to_string(),
            },
        ],
    }
}

/// File-based plan store that loads from prioritized locations
pub struct FilePlanStore;

impl FilePlanStore {
    /// Load recruitment plan from file or fallback to default
    pub fn load() -> Result<RecruitmentPlan> {
        let paths = Self::get_search_paths();
        
        for path in &paths {
            if path.exists() {
                match fs::read_to_string(path) {
                    Ok(content) => {
                        match serde_json::from_str::<RecruitmentPlan>(&content) {
                            Ok(plan) => return Ok(plan),
                            Err(_) => continue, // Try next path on parse error
                        }
                    }
                    Err(_) => continue,
                }
            }
        }
        
        // Fallback to default plan
        Ok(default_plan())
    }

    /// Get prioritized list of file paths to search
    fn get_search_paths() -> Vec<PathBuf> {
        let mut paths = Vec::new();

        // 1. QTRECURIT_DATA environment variable
        if let Ok(data_dir) = std::env::var("QTRECURIT_DATA") {
            paths.push(PathBuf::from(data_dir).join("recruitment_plan.json"));
        }

        // 2. Parent of QTRECURIT_CONFIG
        if let Ok(config_path) = std::env::var("QTRECURIT_CONFIG") {
            if let Some(parent) = Path::new(&config_path).parent() {
                paths.push(parent.join("recruitment_plan.json"));
            }
        }

        // 3. OS data directory (qtadmin subfolder)
        if let Some(data_dir) = dirs::data_dir() {
            paths.push(data_dir.join("qtadmin").join("recruitment_plan.json"));
        }

        // 4. Current working directory
        if let Ok(cwd) = std::env::current_dir() {
            paths.push(cwd.join("recruitment_plan.json"));
        }

        // 5. Fallback to ./recruitment_plan.json
        paths.push(PathBuf::from("./recruitment_plan.json"));

        paths
    }
}

/// Format the recruitment plan as a Markdown status report
pub fn format_status(plan: &RecruitmentPlan) -> String {
    let mut total_headcount = 0u32;
    let mut total_filled = 0u32;
    let mut total_in_progress = 0u32;

    // Aggregate totals
    for pos in &plan.positions {
        total_headcount += pos.headcount;
        total_filled += pos.filled;
        total_in_progress += pos.in_progress;
    }

    let vacancies = total_headcount - total_filled;

    // Extract month and year for title
    let month_display = if let Some((year, month)) = plan.month.split_once('-') {
        format!("{}-{}", year, month)
    } else {
        plan.month.clone()
    };

    let mut output = String::new();

    // Title
    output.push_str(&format!("# {} 招聘计划与进度\n\n", month_display));

    // Table header
    output.push_str("| 岗位 | 编制 | 已入职 | 进行中 | 备注 |\n");
    output.push_str("|------|------|--------|--------|------|\n");

    // Table rows
    for pos in &plan.positions {
        output.push_str(&format!(
            "| {} | {} | {} | {} | {} |\n",
            pos.name, pos.headcount, pos.filled, pos.in_progress, pos.notes
        ));
    }

    // Summary line
    output.push_str(&format!(
        "\n> 编制 {} 人 · 已入职 {} 人 · 进行中 {} 人 · 空缺 {} 人\n",
        total_headcount, total_filled, total_in_progress, vacancies
    ));

    // Date line (hardcoded to June 16 as per spec example)
    output.push_str("> 截至 6 月 16 日\n");

    output
}

/// CLI entry point
pub fn run(args: StatusArgs, _provider: Option<String>) -> Result<()> {
    // Load the plan
    let plan = FilePlanStore::load().context("Failed to load recruitment plan")?;

    // Generate and print the status report
    let report = format_status(&plan);
    print!("{}", report);

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_default_plan_has_8_positions() {
        let plan = default_plan();
        assert_eq!(plan.positions.len(), 8);
        assert_eq!(plan.month, "2026-06");
    }

    #[test]
    fn test_format_status_contains_title() {
        let plan = default_plan();
        let report = format_status(&plan);
        assert!(report.contains("# 2026-06 招聘计划与进度"));
    }

    #[test]
    fn test_format_status_contains_summary() {
        let plan = default_plan();
        let report = format_status(&plan);
        assert!(report.contains("> 编制"));
        assert!(report.contains("已入职"));
        assert!(report.contains("进行中"));
        assert!(report.contains("空缺"));
    }

    #[test]
    fn test_format_status_contains_date() {
        let plan = default_plan();
        let report = format_status(&plan);
        assert!(report.contains("> 截至 6 月 16 日"));
    }

    #[test]
    fn test_format_status_totals() {
        let plan = default_plan();
        let report = format_status(&plan);
        // Total headcount: 3+2+1+2+1+2+1+1 = 13
        assert!(report.contains("编制 13 人"));
        // Total filled: 1+0+1+1+0+0+1+0 = 4
        assert!(report.contains("已入职 4 人"));
        // Total in_progress: 1+2+0+0+1+0+0+1 = 5
        assert!(report.contains("进行中 5 人"));
        // Vacancies: 13 - 4 = 9
        assert!(report.contains("空缺 9 人"));
    }

    #[test]
    fn test_file_plan_store_returns_default_when_no_file() {
        // Ensure no file exists in search paths
        let plan = FilePlanStore::load().unwrap();
        assert_eq!(plan.month, "2026-06");
        assert_eq!(plan.positions.len(), 8);
    }
}
```

## qtrecurit_status

- Token Diff: 73.88%（478/647 token 变更）

### 原始代码

```python
use anyhow::Result;

use crate::cli::StatusArgs;
use crate::connect::EmailFetcher;
use crate::connect::email;
use crate::human;

/// 步骤一（connect）：获取邮件并解析日期范围
fn step_fetch(
    args: &StatusArgs,
) -> Result<(
    Vec<email::MailItem>,
    Option<chrono::NaiveDate>,
    Option<chrono::NaiveDate>,
)> {
    let fetcher = email::LarkCliFetcher;
    let msgs = fetcher.fetch_all()?;
    let items: Vec<email::MailItem> = msgs
        .into_iter()
        .map(|m| email::MailItem {
            subject: m.subject,
            date: m.date,
        })
        .collect();
    let (start, end) = email::resolve_date_range(args.start.clone(), args.end.clone(), args.days);
    Ok((items, start, end))
}

/// 步骤二（human）：生成报告（含漏斗）
fn step_report(
    items: &[email::MailItem],
    start: Option<chrono::NaiveDate>,
    end: Option<chrono::NaiveDate>,
    days: Option<u32>,
) -> String {
    let mut report = human::report::generate_report_from_items(items, start, end, days);
    report.push_str(&crate::funnel::format_funnel(items));
    report
}

pub fn run(args: &StatusArgs) -> Result<()> {
    let (items, start, end) = step_fetch(args)?;
    let report = step_report(&items, start, end, args.days);
    print!("{}", report);
    Ok(())
}
```

### 重写代码

```python
use anyhow::Result;
use chrono::NaiveDate;
use crate::connect::email::{LarkCliFetcher, MailItem};
use crate::human::report::generate_report_from_items;
use crate::funnel::format_funnel;

pub struct StatusArgs {
    pub start: Option<NaiveDate>,
    pub end: Option<NaiveDate>,
    pub days: Option<i64>,
}

fn resolve_date_range(args: &StatusArgs) -> Result<(NaiveDate, NaiveDate)> {
    match (args.start, args.end, args.days) {
        (Some(start), Some(end), None) => Ok((start, end)),
        (Some(start), None, Some(days)) => {
            let end = start + chrono::Duration::days(days);
            Ok((start, end))
        }
        (None, Some(end), Some(days)) => {
            let start = end - chrono::Duration::days(days);
            Ok((start, end))
        }
        (None, None, Some(days)) => {
            let end = chrono::Local::now().date_naive();
            let start = end - chrono::Duration::days(days);
            Ok((start, end))
        }
        (Some(start), None, None) => {
            let end = chrono::Local::now().date_naive();
            Ok((start, end))
        }
        (None, Some(end), None) => {
            let start = end - chrono::Duration::days(30);
            Ok((start, end))
        }
        (None, None, None) => {
            let end = chrono::Local::now().date_naive();
            let start = end - chrono::Duration::days(30);
            Ok((start, end))
        }
        _ => anyhow::bail!("Invalid date range combination: cannot specify both start/end and days"),
    }
}

fn step_fetch(args: &StatusArgs) -> Result<(Vec<MailItem>, NaiveDate, NaiveDate)> {
    let fetcher = LarkCliFetcher::new();
    let raw_messages = fetcher.fetch_all()?;
    
    let items: Vec<MailItem> = raw_messages
        .into_iter()
        .map(|msg| MailItem {
            subject: msg.subject,
            date: msg.date,
        })
        .collect();
    
    let (start_date, end_date) = resolve_date_range(args)?;
    
    Ok((items, start_date, end_date))
}

fn step_report(items: Vec<MailItem>, start_date: NaiveDate, end_date: NaiveDate) -> Result<String> {
    let main_report = generate_report_from_items(&items, start_date, end_date);
    let funnel = format_funnel(&items, start_date, end_date);
    
    Ok(format!("{}\n\n{}", main_report, funnel))
}

pub fn run(args: &StatusArgs) -> Result<()> {
    let (items, start_date, end_date) = step_fetch(args)?;
    let report = step_report(items, start_date, end_date)?;
    println!("{}", report);
    Ok(())
}
```