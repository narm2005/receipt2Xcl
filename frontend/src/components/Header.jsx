import React, { useState } from "react";

export default function Header() {
  const [navOpen, setNavOpen] = useState(false);

  return (
    <header>
      <div className="container">
        <nav className="navbar">
          <a href="#" className="logo">
            <img
              src="/assets/logo.png"
              alt="SlickReceipts.com Logo"
              style={{
                height: "40px",
                marginRight: "10px",
                verticalAlign: "middle",
              }}
            />
            SlickReceipts.com
          </a>
          <ul className={`nav-links${navOpen ? " show" : ""}`}>
            <li><a href="#features">Features</a></li>
            <li><a href="#how-it-works">How It Works</a></li>
            <li><a href="#pricing">Pricing</a></li>
            <li><a href="#testimonials">Testimonials</a></li>
            <li><a href="#contact">Contact</a></li>
          </ul>
          <div
            className="mobile-menu"
            onClick={() => setNavOpen((open) => !open)}
          >
            <i className="fas fa-bars"></i>
          </div>
          <a href="#" className="btn btn-primary">
            Get Started
          </a>
        </nav>
      </div>
    </header>
  );
}