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
