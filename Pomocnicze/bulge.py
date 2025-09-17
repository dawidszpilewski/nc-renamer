import math
import ezdxf

def bulge_from_points_radius(p1, p2, r, ccw=True):
    (x1, y1), (x2, y2) = p1, p2
    d = math.dist(p1, p2)
    theta = 2 * math.asin(d / (2*r))
    bulge = math.tan(theta / 4)
    return bulge if ccw else -bulge

# przykład
doc = ezdxf.new()
msp = doc.modelspace()

p1 = (0, 0)
p2 = (10, 25)
r = 30

bulge = bulge_from_points_radius(p1, p2, r, ccw=True)
msp.add_lwpolyline([(*p1, bulge), (*p2, 0)], format="xyb")

doc.saveas("bulge_arc.dxf")
