// Rendered when the backend rejects the submitted text as not being a valid
// job description. Deliberately shows NO Scam/Legitimate verdict, no confidence
// and no probability graph — the text never reached the ML classifier.
export default function InvalidResult({ message }) {
  return (
    <div className="card result-card invalid">
      <div className="result-header">
        <div>
          <h2 className="card-title">⚠️ Invalid Job Description</h2>
          <p className="card-sub">
            This input was rejected before ML analysis — it does not look like a
            job posting.
          </p>
        </div>
        <div className="verdict-badge badge-invalid">Not analyzed</div>
      </div>

      <div className="invalid-message">
        {message || 'The provided text does not appear to be a valid job description. Please paste a complete job advertisement.'}
      </div>

      <div className="recommendation">
        <strong>What to do:</strong> Paste the full text of a job advertisement
        (title, required skills, project scope, or responsibilities). Short
        greetings, random text and non-job prose will not be classified.
      </div>
    </div>
  )
}
