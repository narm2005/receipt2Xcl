import React from "react";

export default function Testimonials() {
  return (
    <section id="testimonials" className="testimonials">
      <div className="container">
        <div className="text-center">
          <h2 className="section-title">What Our Users Say</h2>
          <p className="section-subtitle">
            Trusted by finance professionals and businesses worldwide
          </p>
        </div>
        <div className="testimonial-grid">
          <div className="testimonial-card">
            <div className="testimonial-content">
              <p>
                "SlickReceipts.com has saved our accounting team over 20 hours per week. The AI extraction is incredibly accurate."
              </p>
            </div>
            <div className="testimonial-author">
              <div className="author-avatar">SR</div>
              <div>
                <h4>Sarah Johnson</h4>
                <p>CFO, TechStart Inc.</p>
              </div>
            </div>
          </div>
          <div className="testimonial-card">
            <div className="testimonial-content">
              <p>
                "The mobile app is a game-changer for our sales team. They can now capture receipts on the go and have them processed instantly."
              </p>
            </div>
            <div className="testimonial-author">
              <div className="author-avatar">MJ</div>
              <div>
                <h4>Michael Roberts</h4>
                <p>Sales Director, Global Solutions</p>
              </div>
            </div>
          </div>
          <div className="testimonial-card">
            <div className="testimonial-content">
              <p>
                "As a freelancer, expense tracking was a nightmare. SmartReceipts.ai made it effortless and saved me hours every month."
              </p>
            </div>
            <div className="testimonial-author">
              <div className="author-avatar">ET</div>
              <div>
                <h4>Emma Thompson</h4>
                <p>Freelance Designer</p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}