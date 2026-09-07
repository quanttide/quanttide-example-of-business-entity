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
