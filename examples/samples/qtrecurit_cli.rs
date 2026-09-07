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
