// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

import './Card.css';

/**
 * Card — surface container with an optional titled header and actions slot.
 *
 * `as` lets a caller render a <section>/<article> when the card is a landmark
 * region; it defaults to a plain <div> so cards can nest freely.
 */
const Card = ({
  as: Tag = 'div',
  title,
  subtitle,
  icon,
  actions,
  padded = true,
  tone = 'neutral',
  className = '',
  children,
  ...rest
}) => (
  <Tag
    className={[
      'ui-card',
      `ui-card--${tone}`,
      padded ? 'ui-card--padded' : '',
      className,
    ].filter(Boolean).join(' ')}
    {...rest}
  >
    {(title || subtitle || actions) && (
      <div className="ui-card-head">
        <div className="ui-card-heading">
          {icon && <span className="ui-card-icon" aria-hidden="true">{icon}</span>}
          <div className="ui-card-heading-text">
            {title && <h3 className="ui-card-title">{title}</h3>}
            {subtitle && <p className="ui-card-subtitle">{subtitle}</p>}
          </div>
        </div>
        {actions && <div className="ui-card-actions">{actions}</div>}
      </div>
    )}
    <div className="ui-card-body">{children}</div>
  </Tag>
);

export default Card;
