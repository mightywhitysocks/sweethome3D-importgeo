package com.eteks.sweethome3d.io;

import java.io.*;
import java.net.*;
import java.util.zip.*;
import javax.xml.parsers.*;
import com.eteks.sweethome3d.model.*;

/**
 * Convertit un ZIP {Home.xml + modeles} (produit par build_home.py) en un vrai
 * fichier .sh3d (avec le Home serialise que le loader SH3D exige).
 *
 *   java -cp SweetHome3D.jar;<cls>  com.eteks.sweethome3d.io.Conv  <in.zip>  <out.sh3d>
 *
 * Doit tourner dans le package com.eteks.sweethome3d.io (setContentContext est
 * package-private) -> compiler en .class sur le classpath, PAS en mode source.
 */
public class Conv {
  public static void main(String[] a) throws Exception {
    File inZip = new File(a[0]).getCanonicalFile();
    String out = a[1];
    // HomeContentContext veut l'URL PLATE du zip (il ajoute lui-meme jar:...!/entree)
    URL zipUrl = inZip.toURI().toURL();

    HomeContentContext ctx = new HomeContentContext(zipUrl, null, true);
    HomeXMLHandler handler = new HomeXMLHandler();
    handler.setContentContext(ctx);

    SAXParserFactory f = SAXParserFactory.newInstance();
    f.setValidating(false);
    try {
      f.setFeature("http://apache.org/xml/features/nonvalidating/load-external-dtd", false);
    } catch (Exception ignore) { }

    try (ZipFile zf = new ZipFile(inZip);
         InputStream in = zf.getInputStream(zf.getEntry("Home.xml"))) {
      f.newSAXParser().parse(new BufferedInputStream(in), handler);
    }
    Home home = handler.getHome();
    java.util.Map<String, Integer> byLevel = new java.util.TreeMap<>();
    for (HomePieceOfFurniture p : home.getFurniture())
      byLevel.merge(p.getLevel() == null ? "<null>" : p.getLevel().getName(), 1, Integer::sum);
    System.out.println("parsed: " + home.getLevels().size() + " niveaux, "
        + home.getFurniture().size() + " meubles " + byLevel + ", "
        + home.getRooms().size() + " pieces-plan");

    new HomeFileRecorder(9, false).writeHome(home, out);
    System.out.println("ecrit : " + out + "  (" + new File(out).length() + " o)");

    // controle : relire le .sh3d ecrit et verifier la repartition par niveau
    Home rr = new HomeFileRecorder(9, false).readHome(out);
    java.util.Map<String, Integer> chk = new java.util.TreeMap<>();
    for (HomePieceOfFurniture p : rr.getFurniture())
      chk.merge(p.getLevel() == null ? "<null>" : p.getLevel().getName(), 1, Integer::sum);
    System.out.println("relu : " + rr.getLevels().size() + " niveaux, meubles " + chk);
  }
}
