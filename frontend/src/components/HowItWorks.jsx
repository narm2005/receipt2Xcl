import React from "react";

export default function HowItWorks() {
  return (
    <section id="how-it-works" className="how-it-works">
      <div className="container">
        <div className="text-center">
          <h2 className="section-title">How It Works</h2>
          <p className="section-subtitle">
            Transforming your receipts into structured data is simple and efficient
          </p>
        </div>
        <div className="steps">
          <div className="step">
            <div className="step-number">1</div>
            <h3>Upload Receipts</h3>
            <p>Take a photo or upload receipt images in any format (JPG, PNG, PDF).</p>
          </div>
          <div className="step">
            <div className="step-number">2</div>
            <h3>AI Processing</h3>
            <p>Our AI extracts text, identifies key data points, and categorizes expenses.</p>
          </div>
          <div className="step">
            <div className="step-number">3</div>
            <h3>Review & Edit</h3>
            <p>Verify the extracted data with our intuitive interface and make adjustments.</p>
          </div>
          <div className="step">
            <div className="step-number">4</div>
            <h3>Export & Analyze</h3>
            <p>Export to Excel or integrate with your accounting software for further analysis.</p>
          </div>
        </div>
      </div>
    </section>
  );
}