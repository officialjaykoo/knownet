mod commands;
mod daemon;
mod error;
mod markdown;
mod protocol;
mod storage;

fn main() {
    if let Err(error) = daemon::run() {
        eprintln!("{error}");
        std::process::exit(1);
    }
}
