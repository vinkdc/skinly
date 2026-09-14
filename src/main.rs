use std::{env, error::Error, fmt, fs, path::PathBuf, process, time::Duration};

use reqwest::{blocking::Client, redirect::Policy, StatusCode};
use serde::Deserialize;

const SESSION_PATH: &str = "/chat/v1/session";

struct Lockfile {
    port: u16,
    password: String,
    protocol: String,
}

#[derive(Debug, Deserialize)]
struct Session {
    game_name: String,
    game_tag: String,
    puuid: String,
    #[serde(default)]
    region: Option<String>,
}

#[derive(Debug)]
struct MessageError(&'static str);

impl fmt::Display for MessageError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.0)
    }
}

impl Error for MessageError {}

fn main() {
    if let Err(error) = run() {
        eprintln!("Error: {error}");
        process::exit(1);
    }
}

fn run() -> Result<(), Box<dyn Error>> {
    let lockfile_path = riot_lockfile_path()?;
    let contents = fs::read_to_string(lockfile_path).map_err(|error| {
        if error.kind() == std::io::ErrorKind::NotFound {
            MessageError("Riot Client is not running (lockfile not found).")
        } else {
            MessageError("Could not read the Riot Client lockfile.")
        }
    })?;
    let lockfile = parse_lockfile(&contents)?;
    let session = fetch_session(&lockfile)?;

    println!("Game name: {}", session.game_name);
    println!("Tag: {}", session.game_tag);
    println!("PUUID: {}", session.puuid);
    if let Some(region) = session.region.filter(|region| !region.is_empty()) {
        println!("Region: {region}");
    }

    Ok(())
}

fn riot_lockfile_path() -> Result<PathBuf, MessageError> {
    let local_app_data = env::var_os("LOCALAPPDATA").ok_or(MessageError(
        "LOCALAPPDATA is not set; this CLI must run on Windows.",
    ))?;
    Ok(PathBuf::from(local_app_data)
        .join("Riot Games")
        .join("Riot Client")
        .join("Config")
        .join("lockfile"))
}

fn parse_lockfile(contents: &str) -> Result<Lockfile, MessageError> {
    let mut fields = contents.trim().split(':');
    let _name = fields.next();
    let _pid = fields.next();
    let port = fields
        .next()
        .and_then(|port| port.parse::<u16>().ok())
        .ok_or(MessageError("The Riot Client lockfile is invalid."))?;
    let password = fields
        .next()
        .filter(|password| !password.is_empty())
        .ok_or(MessageError("The Riot Client lockfile is invalid."))?
        .to_owned();
    let protocol = fields
        .next()
        .filter(|protocol| matches!(*protocol, "http" | "https"))
        .ok_or(MessageError("The Riot Client lockfile is invalid."))?
        .to_owned();

    if fields.next().is_some() {
        return Err(MessageError("The Riot Client lockfile is invalid."));
    }

    Ok(Lockfile {
        port,
        password,
        protocol,
    })
}

fn fetch_session(lockfile: &Lockfile) -> Result<Session, Box<dyn Error>> {
    let client = Client::builder()
        .danger_accept_invalid_certs(true)
        .no_proxy()
        .redirect(Policy::none())
        .connect_timeout(Duration::from_secs(3))
        .timeout(Duration::from_secs(5))
        .build()?;
    let url = format!(
        "{}://127.0.0.1:{}{SESSION_PATH}",
        lockfile.protocol, lockfile.port
    );
    let response = client
        .get(url)
        .basic_auth("riot", Some(&lockfile.password))
        .send()
        .map_err(|_| MessageError("Could not connect to Riot Client."))?;

    if response.status() == StatusCode::UNAUTHORIZED {
        return Err(MessageError("Riot Client rejected its local API credential.").into());
    }
    if !response.status().is_success() {
        return Err(MessageError("Riot Client returned an unexpected response.").into());
    }

    response
        .json::<Session>()
        .map_err(|_| MessageError("Riot Client returned an invalid session response.").into())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_lockfile_fields() {
        let lockfile = parse_lockfile("Riot Client:1234:54321:temporary-secret:https\n").unwrap();

        assert_eq!(lockfile.port, 54321);
        assert_eq!(lockfile.password, "temporary-secret");
        assert_eq!(lockfile.protocol, "https");
    }

    #[test]
    fn rejects_malformed_lockfile_without_exposing_contents() {
        let error = match parse_lockfile("sensitive-content") {
            Ok(_) => panic!("malformed lockfile was accepted"),
            Err(error) => error,
        };

        assert_eq!(error.to_string(), "The Riot Client lockfile is invalid.");
        assert!(!error.to_string().contains("sensitive-content"));
    }

    #[test]
    fn rejects_non_http_protocols() {
        assert!(parse_lockfile("Riot Client:1234:54321:secret:file").is_err());
    }
}
