"use strict";
// Missing upstream model: preserve path references and percentage identity.
class RouteBasic {
  constructor(protocol, path, percentage = 100) {
    this.protocol = protocol; this.path = path; this.percentage = percentage;
  }
  toString() {
    return this.protocol+':'+this.path.map(pool => pool.address.toString()).join(',')+':'+this.percentage;
  }
}
exports.RouteBasic = RouteBasic;
