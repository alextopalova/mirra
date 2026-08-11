import {useSession} from "../state/session";
import {PrimaryButton} from "../components/PrimaryButton";
import "./start.css";
import "./screen.css";

/**
 * The walk-up screen. A shopper decides whether to engage from a couple of
 * metres away in a few seconds, so it answers three questions in order:
 * what is this, what will it do for me, and what does it cost me. The time
 * cost sits directly under the button because that's the last objection
 * before someone commits.
 */
// const STEPS = [
//     {n: "01", title: "Scan", body: "Two photos, taken automatically."},
//     {n: "02", title: "Profile", body: "Your shape and your colour season."},
//     {n: "03", title: "Fitting room", body: "Matching pieces, shown on you."},
// ];

export function StartScreen() {
    const {go} = useSession();

    return (
        <div className="screen start">
            {/* Root-relative, not a repo path: Vite serves frontend/public at
                the site root and nothing outside it, so the file lives there
                and is addressed as "/logo.svg". A relative "youcam_hackathon/..."
                would also have resolved against whatever route the kiosk is
                on, which is never where the file is. */}
            <img className="start-logo" src="/logo.svg" alt="Smart Try-On" />
            <img className="thumbnail" src="/homescreen_pic.png" alt="Thumbnail" />
            <h1 className="start-wordmark">Welcome!</h1>
            <p className="start-lead">
                Find out which pieces in this store were made for your shape and your colours.
            </p>
<div className="start-cta">
                <PrimaryButton label="Start my scan" onClick={() => go("capture")}/>
                <p className="start-time">Takes about 2 minutes</p>
            </div>
            {/* A real sequence, so it's numbered. */}
            {/*<ol className="start-steps">*/}
            {/*    {STEPS.map((s) => (*/}
            {/*        <li key={s.n} className="start-step">*/}
            {/*            <span className="start-step-n">{s.n}</span>*/}
            {/*            <h2 className="start-step-title">{s.title}</h2>*/}
            {/*            <p className="start-step-body">{s.body}</p>*/}
            {/*        </li>*/}
            {/*    ))}*/}
            {/*</ol>*/}
        </div>
    );
}
